from typing import Any, Literal

from django.conf import settings

import posthoganalytics
from langchain_core.output_parsers import SimpleJsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool

SEARCH_TOOL_PROMPT = """
Use this tool to search docs or insights by using natural language.
If the user's question mentions multiple topics, search for each topic separately and combine the results.

# Documentation search

This tool is absolutely NECESSARY to answer PostHog-related questions accurately, as our product and docs change all the time:
- How to use PostHog
- How to use PostHog features
- How to contact support or other humans
- How to report bugs
- How to submit feature requests
- To troubleshoot something
- What default fields and properties are available for events and persons
- …Or anything else PostHog-related

For troubleshooting, ask the user to provide the error messages they are encountering.
If no error message is involved, ask the user to describe their expected results vs. the actual results they're seeing.
You avoid suggesting things that the user has told you they've already tried.

Examples:
- Needs help understanding PostHog concepts
- Has questions about SDK integration or instrumentation
    - e.g. `posthog.capture('event')`, `posthog.captureException(err)`,
    `posthog.identify(userId)`, `capture({ ... })` not working, etc.
- Troubleshooting missing or unexpected data
    - e.g. "Events aren't arriving", "Why don't I see errors on the dashboard?"
- Wants to know more about PostHog the company
- Has questions about incidents or system status
- Has disabled session replay and needs help turning it back on
- Reports an issue with PostHog
- Wants to delete events from PostHog

If the user's question should be satisfied by using insights, do that before answering using documentation.

# Insights search

Use this tool when you can assume that an insight you want to analyze was already created by the user.

Examples:
- Product-specific metrics that most likely exist.
- Common sense metrics that are relevant to the product.
""".strip()

DOCS_SEARCH_RESULTS_TEMPLATE = """Found {count} relevant documentation page(s):

{docs}
<system_reminder>
Use retrieved documentation to answer the user's question if it is relevant to the user's query.
Format the response using Markdown and reference the documentation using hyperlinks.
Every link to docs clearly explicitly be labeled, for example as "(see docs)".
</system_reminder>
""".strip()

DOCS_SEARCH_NO_RESULTS_TEMPLATE = """
No documentation found.

<system_reminder>
Do not answer the user's question if you did not find any documentation. Try rewriting the query.
If after a couple of attempts you still do not find any documentation, suggest the user navigate to the documentation page, which is available at `https://posthog.com/docs`.
</system_reminder>
""".strip()

DOC_ITEM_TEMPLATE = """
# {title}
URL: {url}

{text}
""".strip()

SearchKind = Literal["insights"] | Literal["docs"]


class SearchToolArgs(BaseModel):
    kind: SearchKind = Field(description="Select the entity you want to find")
    query: str = Field(
        description="Describe what you want to find. Include as much details from the context as possible."
    )


class InkeepDocumentContent(BaseModel):
    type: str
    text: str


class InkeepDocumentSource(BaseModel):
    type: str
    content: list[InkeepDocumentContent]


class InkeepDocument(BaseModel):
    type: str
    record_type: str
    url: str
    title: str
    source: InkeepDocumentSource


class InkeepResponse(BaseModel):
    content: list[InkeepDocument]


class SearchTool(MaxTool):
    name: Literal["search"] = "search"
    description: str = SEARCH_TOOL_PROMPT
    thinking_message: str = "Searching for information"
    context_prompt_template: str = "Searches documentation or user data in PostHog (insights)"
    args_schema: type[BaseModel] = SearchToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(self, kind: SearchKind, query: str) -> tuple[str, dict[str, Any] | None]:
        if kind == "docs":
            if not settings.INKEEP_API_KEY:
                return "This tool is not available in this environment.", None
            if self._has_docs_search_feature_flag():
                return await self._search_docs(query), None

        # Used for routing
        return "Search tool executed", SearchToolArgs(kind=kind, query=query).model_dump()

    def _has_docs_search_feature_flag(self) -> bool:
        return posthoganalytics.feature_enabled(
            "max-inkeep-rag-docs-search",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        )

    async def _search_docs(self, query: str) -> str:
        model = ChatOpenAI(
            model="inkeep-rag",
            base_url="https://api.inkeep.com/v1/",
            api_key=settings.INKEEP_API_KEY,
            streaming=False,
            stream_usage=False,
            disable_streaming=True,
        )

        prompt = ChatPromptTemplate.from_messages([("user", "{query}")])
        chain = prompt | model | SimpleJsonOutputParser()
        rag_context_raw = await chain.ainvoke({"query": query})

        if not rag_context_raw or not rag_context_raw.get("content"):
            return DOCS_SEARCH_NO_RESULTS_TEMPLATE

        rag_context = InkeepResponse.model_validate(rag_context_raw)

        docs = []
        for doc in rag_context.content:
            if doc.type != "document":
                continue

            text = doc.source.content[0].text if doc.source.content else ""
            docs.append(DOC_ITEM_TEMPLATE.format(title=doc.title, url=doc.url, text=text))

        if not docs:
            return DOCS_SEARCH_NO_RESULTS_TEMPLATE

        formatted_docs = "\n\n---\n\n".join(docs)
        return DOCS_SEARCH_RESULTS_TEMPLATE.format(count=len(docs), docs=formatted_docs)
