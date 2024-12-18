INITIALIZE_CORE_MEMORY_PROMPT_WITH_URL = """
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

INITIALIZE_CORE_MEMORY_PROMPT_WITH_BUNDLE_IDS = """
Your goal is to describe what the startup with the given application bundle ID{{#bundle_ids.length>1}}s{{/bundle_ids.length>1}} does. The provided bundle ID{{#bundle_ids.length > 1}}s are{{/bundle_ids.length > 1}}{{^bundle_ids.length > 1}} is{{/bundle_ids.length > 1}} {{#bundle_ids}}"{{.}}"{{^last}}, {{/last}}{{/bundle_ids}}.

<sources>
- Retrieve information about app identifiers from app listings of App Store and Google Play.
- If a website URL is provided on the app listing, check the website and retrieve information about the app.
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

FAILED_SCRAPING_MESSAGE = """
Unfortunately, I couldn't find any information about your product. You could edit my initial memory in Settings. Let me help with your request.
""".strip()
