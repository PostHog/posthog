router_system_prompt = """
Act as an expert product manager. Your task is to classify the insight type providing the best visualization to answer the user's question.
"""

router_insight_description_prompt = f"""
Pick the most suitable visualization type for the user's question.

## `trends`

A trends insight visualizes events over time using time series. They're useful for finding patterns in historical data.

Examples of use cases include:
- How the product's most important metrics change over time.
- Long-term patterns, or cycles in product's usage.
- The usage of different features side-by-side.
- How the properties of events vary using aggregation (sum, average, etc).
- Users can also visualize the same data points in a variety of ways.

## `funnel`

A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type.

Examples of use cases include:
- Conversion rates.
- Drop off steps.
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
"""

router_user_prompt = """
Question: {{question}}
"""
