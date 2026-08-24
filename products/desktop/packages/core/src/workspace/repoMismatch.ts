export interface DetectedRepoFullName {
  organization: string;
  repository: string;
}

export function detectRepoFullName(
  detected: DetectedRepoFullName | null,
): string | null {
  if (!detected) {
    return null;
  }
  return `${detected.organization}/${detected.repository}`;
}

export function isRepoMismatch(
  linkedRepo: string | null,
  detectedFullName: string | null,
): boolean {
  if (!linkedRepo || !detectedFullName) {
    return false;
  }
  return detectedFullName.toLowerCase() !== linkedRepo.toLowerCase();
}
