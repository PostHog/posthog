export function shouldLoadCanvasHeadSource(input: {
  dashboardLoaded: boolean;
  lifecycleLoaded: boolean;
  hasPublishedBuild: boolean;
}): boolean {
  return (
    input.dashboardLoaded && input.lifecycleLoaded && !input.hasPublishedBuild
  );
}

export function hasCanvasSource(input: {
  headVersionId: string | null;
  headCode: string | undefined;
}): boolean {
  return !!input.headVersionId || !!input.headCode?.trim();
}
