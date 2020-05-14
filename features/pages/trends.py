from pypom import Page, Region

class TrendsPage(Page):
    URL_TEMPLATE = '/'
    _chart_locator = ('id', 'chart')
    _chart_loader_locator = ('xpath', '//div[@dataAttr=\'loading\']')
    _add_action_event_button_locator = ('xpath', '//button[@dataAttr=\'add-action-event\']')
    _select_action_dropdown_locator = ('text', 'Select action')
    _filter_locator = ('id', 'new-filter')
    _prop_val_dropdown_locator = ('xpath', '//div[@dataAttr=\'prop-val\']')
    _line_graph_locator = ('xpath', '//div[@dataAttr=\'line-graph\']')

    @property
    def line_graph(self):
        return self.find_element(*self._line_graph_locator)

    @property
    def filter_dropdown(self):
        return self.find_element(*self._filter_locator)
    
    @property
    def prop_val_dropdown(self):
        return self.find_element(*self._prop_val_dropdown_locator)

    @property
    def select_action_dropdown(self):
        return self.find_element(*self._select_action_dropdown_locator)

    @property
    def add_action_event_button(self):
        return self.find_element(*self._add_action_event_button_locator)

    @property
    def main_chart(self):
        return self.find_element(*self._chart_locator)

    @property
    def chart_loader(self):
        return self.find_element(*self._chart_loader_locator)

    def wait_for_chart(self):
        self.wait.until(lambda s: not self.chart_loader) #default timeout provided by wait.until