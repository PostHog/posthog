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

        if data:
            # First, flatten the data (i.e., convert it to a list of
            # dictionaries that are each exactly one level deep).  The key for
            # each item designates the name of the column that the item will
            # fall into.
            data = self.flatten_data(data)

            # Get the set of all unique headers, and sort them (unless already provided).
            if not header:
                data = tuple(data)
                headers = []
                for item in data:
                    headers.extend(item.keys())

                unique_fields = list(unique_everseen(headers))

                ordered_fields: Dict[str, Any] = OrderedDict()
                for item in unique_fields:
                    field = item.split(".")
                    field = field[0]
                    if field in ordered_fields:
                        ordered_fields[field].append(item)
                    else:
                        ordered_fields[field] = [item]

                header = []
                for fields in ordered_fields.values():
                    for field in fields:
                        header.append(field)

            # Return your "table", with the headers as the first row.
            if labels:
                yield [labels.get(x, x) for x in header]
            else:
                yield header

            # Create a row for each dictionary, filling in columns for which the
            # item has no data with None values.
            for item in data:
                row = [item.get(key, None) for key in header]
                yield row

        else:
            return []
