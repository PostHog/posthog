INITIALIZE_CORE_MEMORY_PROMPT = """
Your goal is to describe what the startup with the given URL does. The provided URL is "{{url}}".

<sources>
- Check the provided URL. If the URL has a subdomain, check the root domain first and then the subdomain.
- Retrieve information from the websites that provide information about businesses like Crunchbase, G2, LinkedIn, Hackernews, YCombinator, etc.
</sources>

<instructions>
- Describe the product itself and the market where the company operates.
- Describe the target audience of the product.
- Describe the business model of the company.
- List all features that the product has.
- Describe each feature in as much detail as possible.
</instructions>

<format_instructions>
Output your answer in paragraphs with two to three sentences. Separate new paragraphs with a newline.
Answer "No data available." if the given website doesn't exist.
</format_instructions>
"""
