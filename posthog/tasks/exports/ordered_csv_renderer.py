import itertools
from collections import OrderedDict
from typing import Any, Dict, Generator

from more_itertools import unique_everseen
from rest_framework_csv.renderers import CSVRenderer


class OrderedCsvRenderer(
    CSVRenderer,
):
    def tablize(self, data: Any, header: Any = None, labels: Any = None) -> Generator:
        """
        Convert a list of data into a table.
        """
        if not header and hasattr(data, "header"):
            header = data.header

        if not data:
            return []

        # First, flatten the data (i.e., convert it to a list of
        # dictionaries that are each exactly one level deep).  The key for
        # each item designates the name of the column that the item will
        # fall into.
        data = self.flatten_data(data)

        # Get the set of all unique headers, and sort them.
        data = tuple(data)
        all_headers = []
        for item in data:
            all_headers.extend(item.keys())

        unique_fields = list(unique_everseen(all_headers))

        ordered_fields: Dict[str, Any] = OrderedDict()
        for item in unique_fields:
            field = item.split(".")
            field = field[0]
            if field in ordered_fields:
                ordered_fields[field].append(item)
            else:
                ordered_fields[field] = [item]

        flat_ordered_fields = list(itertools.chain(*ordered_fields.values()))
        if not header:
            field_headers = flat_ordered_fields
        else:
            field_headers = header
            for single_header in field_headers:
                if single_header in flat_ordered_fields or single_header not in ordered_fields:
                    continue

                pos_single_header = field_headers.index(single_header)
                field_headers.remove(single_header)
                field_headers[pos_single_header:pos_single_header] = ordered_fields[single_header]

        # Return your "table", with the headers as the first row.
        if labels:
            yield [labels.get(x, x) for x in field_headers]
        else:
            yield field_headers

        # Create a row for each dictionary, filling in columns for which the
        # item has no data with None values.
        for item in data:
            row = [item.get(key, None) for key in field_headers]
            yield row
