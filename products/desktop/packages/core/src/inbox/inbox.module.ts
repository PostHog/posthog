import { ContainerModule } from "inversify";
import { InboxBulkActionService } from "./bulkActionService";
import { DataSourceService } from "./dataSourceService";
import {
  DATA_SOURCE_SERVICE,
  INBOX_BULK_ACTION_SERVICE,
  SIGNAL_REPORT_TASK_SERVICE,
  SIGNAL_SOURCE_SERVICE,
} from "./identifiers";
import { SignalReportTaskService } from "./signalReportTaskService";
import { SignalSourceService } from "./signalSourceService";

export const inboxCoreModule = new ContainerModule(({ bind }) => {
  bind(InboxBulkActionService).toSelf().inSingletonScope();
  bind(INBOX_BULK_ACTION_SERVICE).toService(InboxBulkActionService);

  bind(SignalSourceService).toSelf().inSingletonScope();
  bind(SIGNAL_SOURCE_SERVICE).toService(SignalSourceService);

  bind(SignalReportTaskService).toSelf().inSingletonScope();
  bind(SIGNAL_REPORT_TASK_SERVICE).toService(SignalReportTaskService);

  bind(DataSourceService).toSelf().inSingletonScope();
  bind(DATA_SOURCE_SERVICE).toService(DataSourceService);
});
