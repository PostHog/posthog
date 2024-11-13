SUMMARIZER_RESULTS_PROMPT = """
Here's the full results objects for this question:

{{results}}"""

SUMMARIZER_INSTRUCTION_PROMPT = """
Please answer my earlier question using the results above. Point out interesting trends or anomalies.
Take into account what you know about my product, and offer actionable feedback if possible.
Avoid generic advice - only include feedback if it's directly relevant to my product.
Limit yourself to a few sentences. The answer needs to be high-impact and relevant for me as a Silicon Valley engineer.
"""
