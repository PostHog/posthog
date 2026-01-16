from collections import OrderedDict

from rest_framework_csv.renderers import CSVRenderer


class OrderedCsvRenderer(CSVRenderer):
    @staticmethod
    def group_columns_by_prefix(all_keys: list[str]) -> list[str]:
        """Group columns by their top-level prefix.

        Ensures all 'properties.*' columns are grouped together, all 'distinct_ids.*'
        columns are together, etc. Maintains insertion order within each group.
        """
        ordered_fields: OrderedDict[str, list[str]] = OrderedDict()
        for key in all_keys:
            prefix = key.split(".")[0]
            if prefix in ordered_fields:
                ordered_fields[prefix].append(key)
            else:
                ordered_fields[prefix] = [key]

        return [key for group in ordered_fields.values() for key in group]
