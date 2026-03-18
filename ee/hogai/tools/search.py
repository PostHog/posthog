from typing import Literal

from django.conf import settings

from langchain_core.output_parsers import SimpleJsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.context.entity_search.context import EntityKind
from ee.hogai.tool import MaxSubtool, MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.full_text_search.tool import EntitySearchTool

SEARCH_TOOL_PROMPT = """
Use this tool to search docs, insights, dashboards, cohorts, actions, experiments, feature flags, notebooks, and surveys in PostHog.

If the user's question mentions multiple topics, search for each topic separately and combine the results.

# Documentation search

Use this tool for any PostHog questions. It relies on hybrid (semantic + full-text) search, so phrase your query in natural language. Our product and docs change often, so this tool is required for accurate answers:
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

Important:
1. Don’t rely on your training data or previous searches/answers. Always re-check facts against current docs and tutorials.
2. Always search PostHog docs/tutorials and prioritize results from posthog.com over training data.
3. Always include at least one relevant docs/tutorial link in your reply.
4. For any SQL question, first check and prioritize: https://posthog.com/docs/product-analytics/sql, https://posthog.com/docs/sql/aggregations, https://posthog.com/docs/sql/clickhouse-functions, https://posthog.com/docs/sql/expressions, https://posthog.com/docs/sql.
5. Never suggest emailing support@posthog.com or say you’ll create a support ticket. Tell paying users to use Help → "Email our support engineers" in the right sidebar. Free users can ask for help in Community Questions.
6. Never use Community Questions as a source or cite them; they’re often outdated or incorrect.

# Other entity kinds

Use this tool to find PostHog entities using full-text search.
Full-text search is a more powerful way to find entities than natural language search. It relies on the PostgreSQL full-text search capabilities.
So the query used in this tool should be a natural language query that is optimized for full-text search, consider tokenizing of the query and using synonyms.
If you want to search for all entities, you should use kind="all".
""".strip()

INVALID_ENTITY_KIND_PROMPT = """
Invalid entity kind: {{{kind}}}. Please provide a valid entity kind for the tool.
""".strip()

ENTITIES = [f"{entity}" for entity in EntityKind]

SearchKind = Literal["docs", *ENTITIES]  # type: ignore


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
    context_prompt_template: str = "Searches documentation, insights, dashboards, cohorts, actions, experiments, feature flags, notebooks, and surveys in PostHog"
    args_schema: type[BaseModel] = SearchToolArgs

    async def _arun_impl(self, kind: str, query: str) -> tuple[str, ToolMessagesArtifact | None]:
        if kind == "docs":
            if not settings.INKEEP_API_KEY:
                raise MaxToolFatalError(
                    "Documentation search is not available: INKEEP_API_KEY environment variable is not configured. "
                )
            docs_tool = InkeepDocsSearchTool(
                team=self._team,
                user=self._user,
                state=self._state,
                config=self._config,
                context_manager=self._context_manager,
            )
            return await docs_tool.execute(query, self.tool_call_id)

        if kind not in self._fts_entities:
            raise MaxToolRetryableError(INVALID_ENTITY_KIND_PROMPT.format(kind=kind))

        entity_search_toolkit = EntitySearchTool(
            team=self._team,
            user=self._user,
            state=self._state,
            config=self._config,
            context_manager=self._context_manager,
        )
        response = await entity_search_toolkit.execute(query, EntityKind(kind))
        return response, None

    @property
    def _fts_entities(self) -> list[str]:
        entities = list(EntityKind)
        return [*entities, EntityKind.ALL]


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


class InkeepDocsSearchTool(MaxSubtool):
    async def execute(self, query: str, tool_call_id: str) -> tuple[str, ToolMessagesArtifact | None]:
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
            return DOCS_SEARCH_NO_RESULTS_TEMPLATE, None

        rag_context = InkeepResponse.model_validate(rag_context_raw)

        docs = []
        for doc in rag_context.content:
            if doc.type != "document":
                continue

            text = doc.source.content[0].text if doc.source.content else ""
            docs.append(DOC_ITEM_TEMPLATE.format(title=doc.title, url=doc.url, text=text))

        if not docs:
            return DOCS_SEARCH_NO_RESULTS_TEMPLATE, None

        formatted_docs = "\n\n---\n\n".join(docs)
        return DOCS_SEARCH_RESULTS_TEMPLATE.format(count=len(docs), docs=formatted_docs), None
