import {
  SIGNAL_REPORT_ORIGIN,
  signalReportProduct,
} from "../products/signal-report/product";
import { isSlackLaunch, slackProduct } from "../products/slack/product";
import type { AgentProduct, ProductLaunchConfiguration } from "../sdk/product";

export function selectProduct(
  launch: ProductLaunchConfiguration,
): AgentProduct | undefined {
  if (launch.originProduct === SIGNAL_REPORT_ORIGIN) {
    return signalReportProduct();
  }
  if (isSlackLaunch(launch.originProduct, launch.launchOptions)) {
    return slackProduct();
  }
  return undefined;
}
