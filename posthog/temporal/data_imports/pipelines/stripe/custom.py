# custom functions for stripe sources
from stripe import InvoiceService, StripeClient


class InvoiceListWithAllLines:
    # Invoices have a line field that is a paginated list. This list needs to be expanded for all lines to be included

    def __init__(self, client: StripeClient, params: InvoiceService.ListParams):
        self.client = client
        self.params = params

    def auto_paging_iter(self):
        invoices = self.client.invoices.list(params=self.params)

        for invoice in invoices.auto_paging_iter():
            all_lines = []
            for line in invoice.lines.auto_paging_iter():
                all_lines.append(line)

            invoice.lines.data = all_lines
            invoice.lines.has_more = False
            # type is string but stripe api error message says None is the right way to set this
            invoice.lines.url = None  # type: ignore

            yield invoice
