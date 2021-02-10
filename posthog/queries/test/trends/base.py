from typing import Dict, List, Union


class QueryTest(object):
    name: str
    data: Dict
    filter_data: Dict
    result: Union[Dict, List]

    def __init__(self, name: str, data: Dict, filter_data: Dict, result: Union[Dict, List]) -> None:
        super().__init__()
        self.name = name
        self.data = data
        self.filter_data = filter_data
        self.result = result
