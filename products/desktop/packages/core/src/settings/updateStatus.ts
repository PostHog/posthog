export interface RawUpdateStatus {
  checking?: boolean;
  downloading?: boolean;
  available?: boolean;
  upToDate?: boolean;
  updateReady?: boolean;
  version?: string;
  availableVersion?: string;
  error?: string;
}

export interface DerivedUpdateStatus {
  message?: string;
  type?: "info" | "success" | "error";
  checking?: boolean;
}

export function deriveUpdateStatus(
  status: RawUpdateStatus,
): DerivedUpdateStatus {
  if (status.checking && status.downloading) {
    return { message: "Downloading update...", type: "info", checking: true };
  }
  if (status.checking === false && status.upToDate) {
    return {
      message: "You're on the latest version",
      type: "success",
      checking: false,
    };
  }
  if (status.checking === false && status.updateReady) {
    return {
      message: status.version
        ? `Update ${status.version} ready to install`
        : "Update ready to install",
      type: "success",
      checking: false,
    };
  }
  if (status.checking === false && status.available) {
    return {
      message: status.availableVersion
        ? `Update ${status.availableVersion} available`
        : "Update available",
      type: "success",
      checking: false,
    };
  }
  if (status.checking === false && status.error) {
    return { message: status.error, type: "error", checking: false };
  }
  if (status.checking === false) {
    return { checking: false };
  }
  return {};
}

export interface CheckForUpdatesResult {
  success: boolean;
  errorCode?: "already_checking" | "disabled";
  errorMessage?: string;
}

export interface CheckResultAction {
  updatesDisabled: boolean;
  message: string;
  type: "error";
}

export function resolveCheckResultAction(
  result: CheckForUpdatesResult,
): CheckResultAction | null {
  if (result.success || result.errorCode === "already_checking") {
    return null;
  }
  return {
    updatesDisabled: result.errorCode === "disabled",
    message: result.errorMessage || "Failed to check for updates",
    type: "error",
  };
}
