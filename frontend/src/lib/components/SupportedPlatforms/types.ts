import { ReactNode } from 'react'

export type Feature =
    | 'errorTrackingSuppressionRules'
    | 'errorTrackingExceptionAutocapture'
    | 'sessionReplayLogCapture'
    | 'sessionReplayCanvasCapture'
    | 'sessionReplayCaptureRequests'
    | 'sessionReplayCaptureHeadersAndPayloads'
    | 'sessionReplayAuthorizedDomains'
    | 'sessionReplayMasking'
    | 'autocapture'
    | 'heatmaps'
    | 'deadClicks'
    | 'webVitals'
    | 'surveys'
    | 'logsCapture'

export type PlatformSupport = false | { note?: ReactNode; version?: string }

type SupportedPlatform = 'android' | 'ios' | 'flutter' | 'web' | 'reactNative'
export type PlatformSupportConfig = Partial<Record<SupportedPlatform, PlatformSupport>>
