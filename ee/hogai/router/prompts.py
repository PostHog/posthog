router_system_prompt = """
Act as an expert product manager. Your task is to route the user's request to the appropriate tool given the user's question.
"""

router_user_prompt = """
Question: {{question}}
"""

router_trends_description_prompt = """
Trends insights enable users to plot data from people, events, and properties however they want using time series. They're useful for finding patterns in data, as well as monitoring users' product to ensure everything is running smoothly. For example, using trends, users can analyze:
- How product's most important metrics change over time.
- Long-term patterns, or cycles in product's usage.
- How a specific change affects usage.
- The usage of different features side-by-side.
- How the properties of events vary using aggregation (sum, average, etc).
- Users can also visualize the same data points in a variety of ways.
"""

router_funnel_description_prompt = """
A funnel insight visualizes a sequence of events that users go through in a product. Examples of use cases include:
- Conversion rate.
- Drop off steps.
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
"""
