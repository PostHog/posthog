import re

import yaml
from langchain.output_parsers import OutputFixingParser
from langchain_core.output_parsers import BaseOutputParser
from langchain_openai import ChatOpenAI


class YamlOutputParser(BaseOutputParser):
    """Parser for YAML output that returns dict or list."""

    def parse(self, text: str) -> dict | list:
        """Parse YAML text into generic JSON-like structure."""
        # Strip potential markdown markers, if present
        if "```yaml" in text:
            cleaned_text = re.findall(r"(?:```yaml)((?:.|\n|s)*)(?:```)", text, re.DOTALL)[0]
        else:
            cleaned_text = text.strip()
        return yaml.safe_load(cleaned_text)

    def get_format_instructions(self) -> str:
        """Return format instructions for the parser."""
        return "Return valid YAML format that can be parsed into a dictionary or list."


def load_yaml_from_raw_llm_content(raw_content: str) -> dict | list:
    yaml_parser = YamlOutputParser()
    try:
        content = yaml_parser.parse(raw_content)
        return content
    # Catch only YAML-specific errors that makes sense to try to fix, raise other errors
    except yaml.YAMLError:
        # Try to fix with OutputFixingParser
        llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1)
        fixing_parser = OutputFixingParser.from_llm(parser=yaml_parser, llm=llm, max_retries=1)
        # Allow to raise if the format is still not valid
        return fixing_parser.parse(raw_content)
