import {
  SIGNAL_REPORT_ORIGIN,
  signalReportProduct,
} from "../products/signal-report/product";
import { isSlackLaunch, slackProduct } from "../products/slack/product";
import type { AgentProduct, ProductLaunchConfiguration } from "../sdk/product";

export function selectProduct(
  launch: ProductLaunchConfiguration,
): AgentProduct | undefined {
  if (launch.interactionOrigin === SIGNAL_REPORT_ORIGIN) {
    return signalReportProduct();
  }
  if (isSlackLaunch(launch.interactionOrigin, launch.launchOptions)) {
    return slackProduct();
  }
  return undefined;
}
