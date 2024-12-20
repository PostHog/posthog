INITIALIZE_CORE_MEMORY_WITH_URL_PROMPT = """
Your goal is to describe what the startup with the given URL does.

<sources>
- Check the provided URL. If the URL has a subdomain, check the root domain first and then the subdomain.
- Retrieve information from the websites that provide information about businesses like Crunchbase, G2, LinkedIn, Hackernews, YCombinator, etc.
</sources>

<instructions>
- Describe the product itself and the market where the company operates.
- Describe the target audience of the product.
- Describe the company's business model.
- List all the features of the product and describe each feature in as much detail as possible.
</instructions>

<format_instructions>
Output your answer in paragraphs with two to three sentences. Separate new paragraphs with a new line.
IMPORTANT: do not use any markdown and headers. It must be plain text.
Answer "No data available." if:
- the given website doesn't exist.
- the URL is not a valid website or points to a local environment, for example, localhost, 127.0.0.1, etc.
</format_instructions>
""".strip()

INITIALIZE_CORE_MEMORY_WITH_URL_USER_PROMPT = """
The provided URL is "{{url}}".
""".strip()

INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_PROMPT = """
Your goal is to describe what the startup with the given application bundle IDs does.

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
""".strip()

INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT = """
The provided bundle ID{{#bundle_ids.length > 1}}s are{{/bundle_ids.length > 1}}{{^bundle_ids.length > 1}} is{{/bundle_ids.length > 1}} {{#bundle_ids}}"{{.}}"{{^last}}, {{/last}}{{/bundle_ids}}.
""".strip()

FAILED_SCRAPING_MESSAGE = """
Unfortunately, I couldn't find any information about your product. You could edit my initial memory in Settings. Let me help with your request.
""".strip()
