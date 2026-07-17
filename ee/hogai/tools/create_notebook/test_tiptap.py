from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import MarkdownBlock, SessionReplayBlock

from ee.hogai.artifacts.types import StoredBlock, VisualizationRefBlock
from ee.hogai.tools.create_notebook.tiptap import (
    _parse_inline,
    blocks_to_tiptap_doc,
    markdown_to_tiptap_nodes,
    tiptap_doc_to_text,
)


class TestParseInline(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain text", "hello world", [{"type": "text", "text": "hello world"}]),
            (
                "bold",
                "**bold text**",
                [{"type": "text", "text": "bold text", "marks": [{"type": "bold"}]}],
            ),
            (
                "italic",
                "*italic text*",
                [{"type": "text", "text": "italic text", "marks": [{"type": "italic"}]}],
            ),
            (
                "inline code",
                "`some code`",
                [{"type": "text", "text": "some code", "marks": [{"type": "code"}]}],
            ),
            (
                "link",
                "[click here](https://example.com)",
                [
                    {
                        "type": "text",
                        "text": "click here",
                        "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
                    }
                ],
            ),
            (
                "mixed inline",
                "hello **bold** and *italic*",
                [
                    {"type": "text", "text": "hello "},
                    {"type": "text", "text": "bold", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": " and "},
                    {"type": "text", "text": "italic", "marks": [{"type": "italic"}]},
                ],
            ),
            ("empty", "", []),
        ]
    )
    def test_parse_inline(self, _name, text, expected):
        assert _parse_inline(text) == expected


class TestMarkdownToTiptapNodes(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "h1",
                "# Hello",
                [{"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Hello"}]}],
            ),
            (
                "h3",
                "### Sub heading",
                [
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "Sub heading"}],
                    }
                ],
            ),
            (
                "paragraph",
                "Just a paragraph.",
                [{"type": "paragraph", "content": [{"type": "text", "text": "Just a paragraph."}]}],
            ),
            (
                "code block",
                "```python\nprint('hi')\n```",
                [
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "python"},
                        "content": [{"type": "text", "text": "print('hi')"}],
                    }
                ],
            ),
            (
                "code block no lang",
                "```\nsome code\n```",
                [{"type": "codeBlock", "content": [{"type": "text", "text": "some code"}]}],
            ),
            (
                "bullet list",
                "- item one\n- item two",
                [
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "item one"}],
                                    }
                                ],
                            },
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "item two"}],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            ),
            (
                "ordered list",
                "1. first\n2. second",
                [
                    {
                        "type": "orderedList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "first"}],
                                    }
                                ],
                            },
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "second"}],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            ),
            ("empty string", "", []),
            ("whitespace only", "   \n  \n  ", []),
        ]
    )
    def test_markdown_to_tiptap_nodes(self, _name, markdown, expected):
        assert markdown_to_tiptap_nodes(markdown) == expected

    def test_multi_block_markdown(self):
        md = "# Title\n\nSome text.\n\n- a\n- b\n\n```\ncode\n```"
        nodes = markdown_to_tiptap_nodes(md)
        assert len(nodes) == 4
        assert nodes[0]["type"] == "heading"
        assert nodes[1]["type"] == "paragraph"
        assert nodes[2]["type"] == "bulletList"
        assert nodes[3]["type"] == "codeBlock"


class TestBlocksToTiptapDoc(SimpleTestCase):
    def test_empty_blocks_with_title(self):
        doc = blocks_to_tiptap_doc([], title="My Notebook")
        assert doc["type"] == "doc"
        assert len(doc["content"]) == 1
        assert doc["content"][0]["type"] == "heading"
        assert doc["content"][0]["attrs"]["level"] == 1

    def test_empty_blocks_no_title(self):
        doc = blocks_to_tiptap_doc([])
        assert doc == {"type": "doc", "content": [{"type": "paragraph"}]}

    def test_markdown_block(self):
        blocks = [MarkdownBlock(content="## Section\n\nHello world.")]
        doc = blocks_to_tiptap_doc(blocks)
        content = doc["content"]
        assert content[0]["type"] == "heading"
        assert content[1]["type"] == "paragraph"

    def test_session_replay_block(self):
        blocks = [SessionReplayBlock(session_id="abc123", timestamp_ms=0)]
        doc = blocks_to_tiptap_doc(blocks)
        node = doc["content"][0]
        assert node["type"] == "ph-recording"
        assert node["attrs"]["id"] == "abc123"

    def test_visualization_ref_without_resolver(self):
        blocks = [VisualizationRefBlock(artifact_id="xyz")]
        doc = blocks_to_tiptap_doc(blocks)
        node = doc["content"][0]
        assert node["type"] == "paragraph"
        assert "Visualization: xyz" in node["content"][0]["text"]

    def test_visualization_ref_with_resolver(self):
        def resolver(artifact_id):
            return {
                "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                "name": "My Chart",
            }

        blocks = [VisualizationRefBlock(artifact_id="xyz")]
        doc = blocks_to_tiptap_doc(blocks, resolve_visualization=resolver)
        node = doc["content"][0]
        assert node["type"] == "ph-query"
        assert node["attrs"]["title"] == "My Chart"
        assert node["attrs"]["query"]["kind"] == "InsightVizNode"

    def test_visualization_ref_resolver_returns_none(self):
        blocks = [VisualizationRefBlock(artifact_id="xyz")]
        doc = blocks_to_tiptap_doc(blocks, resolve_visualization=lambda _: None)
        node = doc["content"][0]
        assert node["type"] == "paragraph"
        assert "not found" in node["content"][0]["text"]

    def test_mixed_blocks(self):
        blocks: list[StoredBlock] = [
            MarkdownBlock(content="# Intro\n\nSome text."),
            VisualizationRefBlock(artifact_id="v1"),
            SessionReplayBlock(session_id="s1", timestamp_ms=0),
            MarkdownBlock(content="## Conclusion"),
        ]
        doc = blocks_to_tiptap_doc(blocks, title="Report")
        content = doc["content"]
        # Title heading + heading from markdown + paragraph + viz fallback + recording + conclusion heading
        types = [n["type"] for n in content]
        assert types[0] == "heading"  # title
        assert "ph-recording" in types


class TestTiptapDocToText(SimpleTestCase):
    @parameterized.expand(
        [
            ("none_doc", None, ""),
            ("empty_dict", {}, ""),
            ("empty_content", {"type": "doc", "content": []}, ""),
            (
                "heading",
                {
                    "type": "doc",
                    "content": [
                        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Section"}]}
                    ],
                },
                "## Section",
            ),
            (
                "paragraph",
                {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}]},
                "Hello",
            ),
            (
                "code_block_with_lang",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "codeBlock",
                            "attrs": {"language": "sql"},
                            "content": [{"type": "text", "text": "SELECT 1"}],
                        }
                    ],
                },
                "```sql\nSELECT 1\n```",
            ),
            (
                "bullet_list",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "bulletList",
                            "content": [
                                {
                                    "type": "listItem",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}],
                                },
                                {
                                    "type": "listItem",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "two"}]}],
                                },
                            ],
                        }
                    ],
                },
                "- one\n- two",
            ),
            (
                "ordered_list",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "orderedList",
                            "content": [
                                {
                                    "type": "listItem",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "first"}]}],
                                },
                                {
                                    "type": "listItem",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "second"}]}],
                                },
                            ],
                        }
                    ],
                },
                "1. first\n2. second",
            ),
            (
                "ph_recording",
                {
                    "type": "doc",
                    "content": [{"type": "ph-recording", "attrs": {"id": "sess-abc"}}],
                },
                '<session_replay id="sess-abc" />',
            ),
            (
                "inline_bold",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "important", "marks": [{"type": "bold"}]}],
                        }
                    ],
                },
                "**important**",
            ),
            (
                "inline_link",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "click",
                                    "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
                                }
                            ],
                        }
                    ],
                },
                "[click](https://example.com)",
            ),
        ]
    )
    def test_tiptap_doc_to_text(self, _name, doc, expected):
        assert tiptap_doc_to_text(doc) == expected

    def test_ph_query_node(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {
                        "title": "My Trend",
                        "query": {
                            "kind": "InsightVizNode",
                            "source": {"kind": "TrendsQuery"},
                        },
                    },
                }
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert '<insight title="My Trend"' in result
        assert 'query_kind="InsightVizNode"' in result
        assert 'source_kind="TrendsQuery"' in result
        assert "</insight>" in result

    def test_markdown_notebook_v2_node(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-markdown-notebook",
                    "attrs": {
                        "markdown": '# V2 notebook\n\n<Query query={{"kind":"SavedInsightNode","shortId":"abc"}} />'
                    },
                }
            ],
        }
        assert (
            tiptap_doc_to_text(doc) == '# V2 notebook\n\n<Query query={{"kind":"SavedInsightNode","shortId":"abc"}} />'
        )

    def test_multi_node_doc(self):
        doc = {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Report"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Summary below."}]},
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "item"}]}],
                        }
                    ],
                },
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert "# Report" in result
        assert "Summary below." in result
        assert "- item" in result

    def test_ph_query_node_with_stringified_query(self):
        # Some persisted notebooks store `attrs.query` as a JSON-encoded string rather than a dict.
        # The formatter must parse it instead of crashing with AttributeError.
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {
                        "title": "Pages les plus touchées",
                        "query": '{"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}}',
                    },
                }
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert '<insight title="Pages les plus touchées"' in result
        assert 'query_kind="InsightVizNode"' in result
        assert 'source_kind="TrendsQuery"' in result

    def test_ph_query_node_with_unparseable_query_string(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {"title": "Broken", "query": "not-json"},
                }
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert '<insight title="Broken"' in result
        assert 'query_kind="unknown"' in result
        assert "source_kind=" not in result

    def test_ph_query_node_with_string_source(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {
                        "title": "Edgy",
                        "query": {"kind": "InsightVizNode", "source": "TrendsQuery"},
                    },
                }
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert 'query_kind="InsightVizNode"' in result
        assert "source_kind=" not in result

    def test_ph_query_node_missing_attrs(self):
        doc = {"type": "doc", "content": [{"type": "ph-query"}]}
        result = tiptap_doc_to_text(doc)
        assert '<insight title="Untitled"' in result
        assert 'query_kind="unknown"' in result

    @parameterized.expand(
        [
            ("string_node", "stray string"),
            ("none_node", None),
            ("number_node", 42),
            ("list_node", ["unexpected"]),
        ]
    )
    def test_non_dict_top_level_node_is_skipped(self, _name, bad_node):
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "before"}]},
                bad_node,
                {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert "before" in result
        assert "after" in result

    def test_non_dict_inline_node_is_skipped(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "kept"},
                        "stray inline string",
                        {"type": "text", "text": " also kept"},
                    ],
                },
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert result == "kept also kept"

    def test_non_dict_list_item_is_skipped(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        "stray",
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "real"}]}],
                        },
                    ],
                }
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert "- real" in result

    def test_string_attrs_are_coerced_or_ignored(self):
        # Even if `attrs` itself is a string, we should not crash.
        doc = {
            "type": "doc",
            "content": [
                {"type": "ph-recording", "attrs": "not-a-dict"},
                {
                    "type": "ph-recording",
                    "attrs": '{"id": "sess-json"}',
                },
            ],
        }
        result = tiptap_doc_to_text(doc)
        assert '<session_replay id="unknown" />' in result
        assert '<session_replay id="sess-json" />' in result
