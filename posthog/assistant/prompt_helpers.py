from abc import ABC, abstractmethod


class BasePrompt(ABC):
    def _clean_line(self, line: str) -> str:
        return line.replace("\n", " ")

    def _get_xml_tag(self, tag_name: str, content: str) -> str:
        return f"\n<{tag_name}>\n{content.strip()}\n</{tag_name}>\n"

    @abstractmethod
    def generate_prompt(self) -> str:
        raise NotImplementedError()
