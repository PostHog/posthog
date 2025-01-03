INITIALIZE_CORE_MEMORY_WITH_URL_PROMPT = """
Your goal is to describe what the startup with the given URL does.
""".strip()

INITIALIZE_CORE_MEMORY_WITH_URL_USER_PROMPT = """
<sources>
- Check the provided URL. If the URL has a subdomain, check the root domain first and then the subdomain. For example, if the URL is https://us.posthog.com, check https://posthog.com first and then https://us.posthog.com.
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
IMPORTANT: DO NOT OUTPUT markdown or headers. It must be plain text.

Answer a single sentence "No data available." if:
- the given website doesn't exist, or the URL does not match any of the sources given.
- the URL is not a valid website or points to a local environment, for example, localhost, 127.0.0.1, etc.
</format_instructions>

The provided URL is "{{url}}".
""".strip()

INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_PROMPT = """
Your goal is to describe what the startup with the given application bundle IDs does.
""".strip()

INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT = """
<sources>
- Retrieve information about app identifiers from app listings of App Store and Google Play.
- If a website URL is provided on the app listing, check the website and retrieve information about the app.
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
IMPORTANT: DO NOT OUTPUT markdown or headers. It must be plain text.

Answer a single sentence "No data available." if:
- the given website doesn't exist, or the URL does not match any of the sources given.
- the URL is not a valid website or points to a local environment, for example, localhost, 127.0.0.1, etc.
</format_instructions>

The provided bundle ID{{#bundle_ids.length > 1}}s are{{/bundle_ids.length > 1}}{{^bundle_ids.length > 1}} is{{/bundle_ids.length > 1}} {{#bundle_ids}}"{{.}}"{{^last}}, {{/last}}{{/bundle_ids}}.
""".strip()

FAILED_SCRAPING_MESSAGE = """
Unfortunately, I couldn't find any information about your product. You could edit my initial memory in Settings. Let me help with your request.
""".strip()

COMPRESSION_PROMPT = """
Your goal is to shorten paragraphs in the given text to have only a single sentence for each paragraph, preserving the original meaning and maintaining the cohesiveness of the text. Remove all found headers. You must keep the original structure. Remove linking words. Do not use markdown or any other text formatting.
""".strip()
