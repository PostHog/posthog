export const loadReviewPage = () =>
  import("./ReviewPage").then((module) => ({ default: module.ReviewPage }));

export const loadCloudReviewPage = () =>
  import("./CloudReviewPage").then((module) => ({
    default: module.CloudReviewPage,
  }));

export function preloadReviewPages(): void {
  void loadReviewPage();
  void loadCloudReviewPage();
}
