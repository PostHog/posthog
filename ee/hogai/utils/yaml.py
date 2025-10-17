import yaml
import structlog
from langchain.output_parsers import OutputFixingParser
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import BaseOutputParser
from langchain_openai import ChatOpenAI

logger = structlog.get_logger(__name__)


class YamlOutputParser(BaseOutputParser):
    """Parser for YAML output that returns dict or list."""

    def parse(self, text: str) -> dict | list:
        """Parse YAML text into generic JSON-like structure."""
        # Strip potential markdown markers, if present
        try:
            cleaned_text = text.strip("```yaml").strip("```").strip()  # noqa: B005 stable approach with streaming chunks
            return yaml.safe_load(cleaned_text)
        except yaml.YAMLError as e:
            # Catch only YAML-specific errors that makes sense to try to fix, raise other errors
            raise OutputParserException(f"Error loading LLM-generated YAML content into JSON: {e}") from e

    def get_format_instructions(self) -> str:
        """Return format instructions for the parser."""
        return "Return valid YAML format that can be parsed into a dictionary or list."


def load_yaml_from_raw_llm_content(raw_content: str, final_validation: bool = False) -> dict | list:
    yaml_parser = YamlOutputParser()
    try:
        content = yaml_parser.parse(raw_content)
        return content
    except OutputParserException:
        if not final_validation:
            # In-the-middle-of-stream chunks could be invalid, no need to fix them
            raise
        # Try to fix with OutputFixingParser
        llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1)
        fixing_parser = OutputFixingParser.from_llm(parser=yaml_parser, llm=llm, max_retries=1)
        # Allow to raise if the format is still not valid
        return fixing_parser.parse(raw_content)
