# Max AI - Your Data Detective 🕵️

Max is PostHog's AI assistant that helps you analyze data, create insights, and navigate the platform. Think of Max as your data detective - always ready to dig into your analytics and find the answers you need.

This guide breaks down all the message types Max uses so you can get the most out of your AI-powered data analysis.

## Message Types

Max speaks in different message types, each serving a specific purpose. Here's what each one means and when you'll see them:

### 1. HumanMessage 👤

**What it is**: Your messages to Max

This is you talking to Max! Every time you ask a question or make a request, it becomes a HumanMessage.

**What Max sees**:

```python
HumanMessage(
    content="Show me user retention trends for the last month",
    ui_context=MaxUIContext(...)  # What page you're on, what data you're viewing
)
```

**When you'll see this**: Every message you send in the chat

**Pro tip**: Max gets context about what page you're on and what data you're looking at, so you can ask things like "analyze this dashboard" without being super specific.

### 2. AssistantMessage 🤖

**What it is**: Max's regular chat responses

This is Max talking back to you - explanations, answers, follow-up questions, you name it.

**What happens behind the scenes**:

```python
AssistantMessage(
    content="I'll analyze user retention for the last month. Let me pull that data...",
    tool_calls=[AssistantToolCall(...)],  # Max might call tools to get data
    meta=AssistantMessageMetadata(forms=[...])  # Sometimes Max asks for more info
)
```

**When you'll see this**: Most of Max's responses are AssistantMessages

**What to expect**: Max might ask follow-up questions or present you with options to refine your request. Sometimes these messages trigger Max to use tools behind the scenes.

### 3. ReasoningMessage 🧠

**What it is**: Max showing you its thinking

Ever wondered what's going on in Max's head? ReasoningMessages let you peek behind the curtain and see exactly how Max approaches your request.

**What you'll see**:

```python
ReasoningMessage(
    content="Creating trends query",
    substeps=["Identifying key events", "Setting time range", "Configuring filters"]
)
```

**When you'll see this**: During complex analysis when Max is working through multiple steps

**Common reasoning messages**:

-   "Picking relevant events and properties" - Max is figuring out what data to analyze
-   "Creating trends query" - Max is building your visualization
-   "Coming up with an insight" - Max is planning how to answer your question
-   "Checking PostHog docs" - Max is looking up information for you

**Why this matters**: Understanding Max's reasoning helps you ask better questions and trust the results more.

### 4. VisualizationMessage 📊

**What it is**: The actual data insights Max creates for you

This is the money shot - the charts, graphs, and data analysis you asked for. When Max builds you an insight, it shows up as a VisualizationMessage.

**What's inside**:

```python
VisualizationMessage(
    query="Show user retention for mobile users",
    answer=AssistantRetentionQuery(...),  # The actual PostHog query
    plan="Weekly cohorts with core action filters",
    initiator="message_id_that_started_this"  # Links back to your question
)
```

**When you'll see this**: After Max analyzes your data and creates insights

**What Max can build for you**:

-   **AssistantTrendsQuery**: How metrics change over time (DAU, page views, etc.)
-   **AssistantFunnelsQuery**: Conversion rates through your user journey
-   **AssistantRetentionQuery**: How well you keep users coming back
-   **AssistantHogQLQuery**: Custom SQL queries for power users

**Pro tip**: The visualization is a real PostHog insight that gets saved to your account - you can modify it, add it to dashboards, or share it with your team.

### 5. FailureMessage ❌

**What it is**: When things go sideways

Even data detectives hit dead ends sometimes. FailureMessages pop up when Max can't complete your request for some reason.

**What you'll see**:

```python
FailureMessage(
    content="I couldn't generate the funnel analysis because those events aren't in your data."
)
```

**When this happens**: Max encounters an error or can't find the data you're looking for

**Common scenarios**:

-   Events or properties don't exist in your data
-   Query is too complex or times out
-   System hiccups (hey, it happens)

**What to do**: Read the error message - Max usually gives you helpful hints about what went wrong and how to fix it.

### 6. AssistantToolCallMessage 🔧

**What it is**: Max using its superpowers

Max has a toolkit of specialized abilities. When it uses one of these tools, you'll see an AssistantToolCallMessage.

**What's happening**:

```python
AssistantToolCallMessage(
    content="Navigated to insights page",
    tool_call_id="unique_call_id",
    ui_payload={"page_key": "insights"},  # This might update your UI
    visible=True  # Whether you see this message
)
```

**When you'll see this**: Max is doing something beyond just chatting - taking actions or fetching data

**Max's toolkit includes**:

-   `search_session_recordings`: Find relevant user sessions
-   `generate_hogql_query`: Create custom HogQL queries
-   `create_and_query_insight`: Build new PostHog insights
-   `navigate`: Jump to different pages in PostHog
-   `search_documentation`: Look up help articles and guides

**Pro tip**: Some tool calls are invisible - Max might use tools behind the scenes without showing you every step.

## Status Events

### AssistantGenerationStatusEvent ⚡

**What it is**: Max letting you know it's working

Sometimes Max needs a moment to think. AssistantGenerationStatusEvents keep you posted on what's happening.

**Behind the scenes**:

```python
AssistantGenerationStatusEvent(
    type=AssistantGenerationStatusType.ACK  # Max is working on your request
)
```

**When you'll see this**: During longer operations when Max is crunching data or building complex insights

**What it means**: Max hasn't forgotten about you - it's just working hard on your request. Complex analytics take time!

## How Max Actually Works (For Developers)

### Creating HumanMessages

```python
# Basic human message
message = HumanMessage(content="What's the trend of page views?")

# With UI context (this is the magic sauce)
message = HumanMessage(
    content="Analyze this data",
    ui_context=MaxUIContext(dashboards=[...], insights=[...])  # Max knows what you're looking at
)
```

### How Max Generates ReasoningMessages

```python
# Max's internal reasoning system
def get_reasoning_message(self, node_name: AssistantNodeName) -> ReasoningMessage:
    match node_name:
        case AssistantNodeName.TRENDS_GENERATOR:
            return ReasoningMessage(content="Creating trends query")
        case AssistantNodeName.QUERY_PLANNER:
            return ReasoningMessage(
                content="Picking relevant events and properties",
                substeps=["Analyzing user request", "Identifying data sources"]
            )
```

### Building VisualizationMessages

```python
# When Max creates an insight for you
visualization = VisualizationMessage(
    query=self._get_insight_plan(state),
    answer=parsed_query,  # AssistantTrendsQuery, AssistantFunnelsQuery, etc.
    plan="Analysis execution plan",
    initiator=state.start_id  # Links back to your original question
)
```

### Tool Call Implementation

```python
# How MaxTools work
def _run_impl(self, page_key: str) -> tuple[str, Any]:
    return f"Navigated to {page_key}", {"page_key": page_key}

# This becomes an AssistantToolCallMessage with ui_payload
```

## How Max's Brain Works

Max isn't just a simple chatbot - it's a **LangGraph**, which is basically a sophisticated AI system with multiple specialized components working together.

### The Core Team

-   **Root Node**: The traffic controller - figures out what you want and routes your request
-   **Memory System**: Remembers your preferences and learns from your usage patterns
-   **Query Planner**: The strategist - decides the best way to analyze your data
-   **Query Executor**: The workhorse - actually runs your queries and formats the results

### The Specialists

Max has different "specialists" for different types of analysis:

-   **Trends Generator**: Your time-series expert (AssistantTrendsQuery)
-   **Funnel Generator**: The conversion analysis guru (AssistantFunnelsQuery)
-   **Retention Generator**: Masters of cohort analysis (AssistantRetentionQuery)
-   **SQL Generator**: For when you need custom HogQL magic (AssistantHogQLQuery)

### The Support Crew

-   **Documentation Search**: Finds answers in PostHog docs when you need help
-   **Title Generator**: Comes up with meaningful names for your insights
-   **Memory Collector**: Learns from your conversations to get better over time

## Getting the Most Out of Max

### How to Ask Better Questions

1. **Be specific**: "Show retention for mobile users who completed onboarding" beats "show retention"
2. **Give context**: Tell Max what you're trying to figure out - "I want to understand why signups dropped last week"
3. **Iterate**: Start with a basic question, then ask Max to dig deeper or adjust the analysis

### Understanding Max's Responses

-   **ReasoningMessages** = Max showing its work (great for learning how to think about data)
-   **VisualizationMessages** = The actual insights you asked for
-   **AssistantToolCallMessages** = Max using its special abilities
-   **FailureMessages** = When things don't work out (but Max usually tells you why)

### Max's Superpowers

-   Max can navigate PostHog for you - just say "go to insights" or "show me my dashboards"
-   Complex analysis might involve Max using multiple tools in sequence
-   Some tools work invisibly while others show you exactly what's happening

## The Tech Stack (For the Curious)

Max is built on some pretty cool tech:

-   **LangGraph**: Manages conversation state and complex workflows
-   **LangChain**: Coordinates all the AI tools and integrations
-   **OpenAI GPT-4**: The brain that understands what you're asking
-   **Django**: Keeps track of your conversations and context
-   **Redis**: Streams responses to you in real-time

This setup lets Max:

-   Remember what you talked about earlier in the conversation
-   Learn your preferences and data patterns over time
-   Know what page you're on and what data you're looking at
-   Handle complex multi-step analysis without losing track

## A Typical Conversation with Max

Here's what happens when you ask Max to analyze your signup funnel:

1. **You**: `HumanMessage(content="Show me conversion rates for our signup flow")`
2. **Max**: `ReasoningMessage(content="Coming up with an insight")` - Max is thinking
3. **Max**: `ReasoningMessage(content="Picking relevant events and properties")` - Max is figuring out what data to use
4. **Max**: `ReasoningMessage(content="Creating funnel query")` - Max is building the analysis
5. **Max**: `VisualizationMessage(query="Signup flow conversion", answer=AssistantFunnelsQuery(...))` - The actual insight appears
6. **Max**: `AssistantMessage(content="Here's your signup conversion analysis...")` - Max explains what you're seeing

Notice how Max shows its work before delivering the goods? That's the transparency that makes Max special.

## When Things Go Wrong (It Happens)

**Max seems stuck?** Look for FailureMessages that explain what's up

**Results look funky?** Ask Max to show its reasoning or try asking the question differently

**Tools not working?** Make sure you're on the right page - some tools only work in certain contexts

**Need more help?** Ask Max to search the docs or navigate to the right page for you

## Want to Extend Max?

Max is built to be extensible. If you want to add new capabilities:

1. **For new query types**: Check the existing README in `ee/hogai/` for extending AssistantTrendsQuery, AssistantFunnelsQuery, etc.
2. **For new tools**: Implement a MaxTool following the patterns in `products/*/backend/max_tools.py`
3. **Questions?** Hit up the #team-max-ai channel in Slack

---

Max is always learning and getting better. Your feedback helps make the AI assistant more useful for everyone building great products with PostHog 🦔
