from parameterized import parameterized

from products.conversations.backend.services.email_links import recover_links_from_html


class TestRecoverLinksFromHtml:
    def test_recovers_link_dropped_from_flattened_plain_text(self) -> None:
        text = "Please confirm the forward.\nAttiva l'inoltro\nThanks"
        html = '<p>Please confirm the forward.</p><a href="https://host.example/activate?t=abc">Attiva l\'inoltro</a>'
        result = recover_links_from_html(text, html)
        assert "[Attiva l'inoltro](https://host.example/activate?t=abc)" in result

    def test_leaves_text_untouched_when_url_already_present(self) -> None:
        text = "Confirm at https://host.example/activate?t=abc now"
        html = '<a href="https://host.example/activate?t=abc">Confirm</a>'
        assert recover_links_from_html(text, html) == text

    def test_only_first_occurrence_is_linked(self) -> None:
        text = "click here and also click here"
        html = '<a href="https://host.example/go">click here</a>'
        result = recover_links_from_html(text, html)
        assert result == "[click here](https://host.example/go) and also click here"

    @parameterized.expand(
        [
            ("no_html", "just text", ""),
            ("no_text", "", "<a href='https://host.example'>x</a>"),
        ]
    )
    def test_noop_without_both_sides(self, _name: str, text: str, html: str) -> None:
        assert recover_links_from_html(text, html) == text

    def test_ignores_non_http_and_labelless_anchors(self) -> None:
        text = "mail me or open the app"
        html = '<a href="mailto:x@example.com">mail me</a><a href="https://host.example"></a>'
        assert recover_links_from_html(text, html) == text

    def test_skips_label_missing_from_text(self) -> None:
        text = "Only the footer survived"
        html = '<a href="https://host.example/cta">Activate now</a>'
        assert recover_links_from_html(text, html) == text

    def test_does_not_nest_when_label_is_substring_of_another(self) -> None:
        text = "Attiva l'inoltro"
        html = (
            '<a href="https://host.example/activate">Attiva l\'inoltro</a>'
            '<a href="https://host.example/other">inoltro</a>'
        )
        result = recover_links_from_html(text, html)
        assert result == "[Attiva l'inoltro](https://host.example/activate)"

    def test_escapes_parentheses_in_href(self) -> None:
        text = "Read the docs here"
        html = '<a href="https://host.example/wiki/Foo_(bar)">Read the docs here</a>'
        result = recover_links_from_html(text, html)
        assert result == "[Read the docs here](https://host.example/wiki/Foo_%28bar%29)"

    def test_links_earliest_occurrence_across_multiple_labels(self) -> None:
        text = "First open the guide then confirm your account"
        html = (
            '<a href="https://host.example/confirm">confirm your account</a>'
            '<a href="https://host.example/guide">the guide</a>'
        )
        result = recover_links_from_html(text, html)
        assert result == (
            "First open [the guide](https://host.example/guide) then "
            "[confirm your account](https://host.example/confirm)"
        )
