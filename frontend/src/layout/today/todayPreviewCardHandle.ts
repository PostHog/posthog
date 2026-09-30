import { PreviewCard } from '@base-ui/react/preview-card'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { TodayWorkItem } from './todayWorkItems'

export type TodayPreviewPayload = { kind: 'session'; item: TodayWorkItem } | { kind: 'space'; space: ChannelDTOApi }

/** One card for the whole rail. Rows are only triggers, so moving between rows swaps the card with no new delay. */
export const todayPreviewCardHandle = PreviewCard.createHandle<TodayPreviewPayload>()
