import { chromium } from "playwright";

const browser = await chromium.launch();
const shots = [
  [
    "features-posthog-objects-posthogobjectpageview--feature-flag",
    "flag",
    1100,
  ],
  [
    "features-posthog-objects-posthogobjectpageview--experiment",
    "experiment",
    1100,
  ],
  ["features-posthog-objects-posthogobjectpageview--sql-query", "sql", 1100],
  [
    "features-posthog-objects-posthogobjectpageview--feature-flag",
    "flag-narrow",
    640,
  ],
];
for (const [id, name, width] of shots) {
  const page = await browser.newPage({ viewport: { width, height: 1200 } });
  await page.goto(`http://localhost:6006/iframe.html?id=${id}&viewMode=story`, {
    waitUntil: "networkidle",
  });
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `/tmp/v1-${name}.png`, fullPage: true });
  await page.close();
}
await browser.close();
console.log("done");
