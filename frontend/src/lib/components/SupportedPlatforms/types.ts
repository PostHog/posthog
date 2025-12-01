import { ReactNode } from 'react'

export type Feature = 'errorTrackingSuppressionRules' | 'errorTrackingExceptionAutocapture'
export type PlatformSupport = false | { note?: ReactNode; version?: string }

type SupportedPlatform = 'android' | 'ios' | 'flutter' | 'web' | 'reactNative'
export type PlatformSupportConfig = Partial<Record<SupportedPlatform, PlatformSupport>>
