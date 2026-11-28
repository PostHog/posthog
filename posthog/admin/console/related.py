from django import forms
from django.core.paginator import Paginator
from django.db.models import Model
from django.http import HttpRequest
from django.urls import reverse

from posthog.admin.console.records import RECORD_TYPES, RecordType, Relation
from posthog.admin.console.tools import Cell, FieldGroup, Filters, Page, Paging, Row, Table
from posthog.dataclasses import frozen

RELATED_PREVIEW_SIZE = 5
RELATED_PER_PAGE = 100


@frozen
class RelatedLink:
    title: str
    href: str
    record_id: str
    detail: str = ""


@frozen
class RelatedPreview:
    relation: Relation
    links: tuple[RelatedLink, ...]
    total: int
    all_url: str
    # Templates call any callable they meet, so the template reads this flag and never `relation.search`.
    searchable: bool


class RelatedSearchForm(forms.Form):
    search = forms.CharField(required=False, label="Search")


class RelatedRecords:
    """The records related to one record: the first few under its page header, and all of them on a page of their own."""

    def __init__(self, record_type: RecordType, obj: Model) -> None:
        self.record_type = record_type
        self.obj = obj

    def url(self, relation: Relation) -> str:
        return reverse(self.record_type.related_url_name, kwargs={"pk": self.obj.pk, "relation_key": relation.key})

    @staticmethod
    def link(relation: Relation, row: Model) -> RelatedLink:
        target_type = RECORD_TYPES[relation.target]
        record = relation.record(row)
        return RelatedLink(
            title=target_type.title(record),
            href=target_type.url(record),
            record_id=target_type.short_id(record),
            detail=relation.detail_of(row) if relation.detail_of is not None else "",
        )

    def previews(self) -> list[RelatedPreview]:
        previews = []
        for relation in self.record_type.relations():
            rows = relation.rows(self.obj.pk)
            # One row past the preview tells whether more exist, so the count query runs only when they do.
            first = list(rows[: RELATED_PREVIEW_SIZE + 1])
            total = len(first) if len(first) <= RELATED_PREVIEW_SIZE else rows.count()
            previews.append(
                RelatedPreview(
                    relation=relation,
                    links=tuple(self.link(relation, row) for row in first[:RELATED_PREVIEW_SIZE]),
                    total=total,
                    all_url=self.url(relation),
                    searchable=relation.search is not None,
                )
            )
        return previews

    def page(self, request: HttpRequest, relation: Relation) -> Page:
        rows = relation.rows(self.obj.pk)
        search_form = RelatedSearchForm(request.GET) if relation.search is not None else None
        search = ""
        if search_form is not None and search_form.is_valid():
            search = search_form.cleaned_data["search"].strip()
        if search and relation.search is not None:
            rows = relation.search(rows, search)
        page = Paginator(rows, RELATED_PER_PAGE).get_page(request.GET.get("page"))
        query = request.GET.copy()

        def page_url(number: int) -> str:
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        table = Table(
            columns=(RECORD_TYPES[relation.target].label, "ID", *relation.columns),
            rows=tuple(self._row(relation, row) for row in page.object_list),
            empty_text="Nothing matches the search." if search else "None.",
        )
        paging = Paging(
            number=page.number,
            num_pages=page.paginator.num_pages,
            summary=f"{page.paginator.count:,} in all",
            previous_url=page_url(page.previous_page_number()) if page.has_previous() else None,
            next_url=page_url(page.next_page_number()) if page.has_next() else None,
        )
        filters = (
            (
                Filters(
                    form=search_form,
                    groups=(FieldGroup(title="Search", field_names=("search",)),),
                    submit_label="Search",
                    compact=True,
                ),
            )
            if search_form is not None
            else ()
        )
        return Page(blocks=(*filters, table, *((paging,) if page.paginator.count else ())))

    @classmethod
    def _row(cls, relation: Relation, row: Model) -> Row:
        link = cls.link(relation, row)
        cells = relation.cells_of(row) if relation.cells_of is not None else ()
        return Row(
            cells=(
                Cell(text=link.title, href=link.href),
                Cell(text=str(relation.record(row).pk), mono=True),
                *(Cell(text=text) for text in cells),
            )
        )
