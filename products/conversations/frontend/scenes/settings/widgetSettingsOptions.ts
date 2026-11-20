import { ConversationsSettings } from '~/types'

export const WIDGET_COLORS = ['#1d4aff', '#00aaff', '#00cc44', '#ffaa00', '#ff4444', '#9b59b6', '#1abc9c', '#000000']

export const WIDGET_POSITION_OPTIONS: {
    value: NonNullable<ConversationsSettings['widget_position']>
    label: string
}[] = [
    { value: 'bottom_right', label: 'Bottom right' },
    { value: 'bottom_left', label: 'Bottom left' },
    { value: 'top_right', label: 'Top right' },
    { value: 'top_left', label: 'Top left' },
]
