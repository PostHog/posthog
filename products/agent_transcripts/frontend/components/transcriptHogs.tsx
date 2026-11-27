import * as cursorPng from '@posthog/brand/hoggies/png/cursor'
import * as errorPng from '@posthog/brand/hoggies/png/error'
import * as heartPng from '@posthog/brand/hoggies/png/heart'
import * as highlighterPng from '@posthog/brand/hoggies/png/highlighter'
import * as hourglassPng from '@posthog/brand/hoggies/png/hourglass'
import * as ipadPng from '@posthog/brand/hoggies/png/ipad'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import * as officeWorkerPng from '@posthog/brand/hoggies/png/office-worker'
import * as partyPng from '@posthog/brand/hoggies/png/party'
import * as readingPng from '@posthog/brand/hoggies/png/reading'
import * as robotPng from '@posthog/brand/hoggies/png/robot'
import * as rocketPng from '@posthog/brand/hoggies/png/rocket'
import * as workmaxxingPng from '@posthog/brand/hoggies/png/workmaxxing'

import { pngHoggie } from 'lib/brand/hoggies'

/** Hedgehogs for each step and outcome of the transcript page. */
export const AgentPickerHog = pngHoggie(robotPng)
export const TerminalAgentHog = pngHoggie(workmaxxingPng)
export const CursorHog = pngHoggie(cursorPng)
export const ChatAppHog = pngHoggie(ipadPng)
export const OtherAgentHog = pngHoggie(officeWorkerPng)
export const UploadHog = pngHoggie(mailboxPng)
export const SendingHog = pngHoggie(rocketPng)
export const CheckingHog = pngHoggie(hourglassPng)
export const SecretFoundHog = pngHoggie(magnifyingGlassPng)
export const InReviewHog = pngHoggie(readingPng)
export const ChangesRequestedHog = pngHoggie(highlighterPng)
export const ApprovedHog = pngHoggie(partyPng)
export const DeclinedHog = pngHoggie(heartPng)
export const LoadErrorHog = pngHoggie(errorPng)
