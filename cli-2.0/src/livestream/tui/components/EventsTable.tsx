import React from 'react'
import { Box, Text } from 'ink'
import { colors, getEventColor } from '../colors.js'
import { sanitize } from '../sanitize.js'
import type { EventMsg } from '../../types.js'

type EventsTableProps = {
  events: EventMsg[]
  selectedIndex: number
  height: number
}

const formatTimestamp = (timestamp: string | number): string => {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return date.toLocaleTimeString()
}

const truncate = (str: string, maxLength: number): string => {
  if (str.length <= maxLength) return str
  return str.slice(0, maxLength - 1) + '…'
}

const EventRow = ({
  event,
  isSelected,
  width,
}: {
  event: EventMsg
  isSelected: boolean
  width: number
}) => {
  const eventColor = getEventColor(event.event)
  const prefix = isSelected ? '▸' : ' '

  // Calculate column widths
  const eventWidth = 25
  const distinctIdWidth = 30
  const timeWidth = 8
  const urlWidth = Math.max(20, width - eventWidth - distinctIdWidth - timeWidth - 10)

  // Get URL from properties - sanitize all user-controlled fields
  const url = sanitize(event.properties?.$current_url ?? '')
  const displayUrl = url.replace(/^https?:\/\//, '').replace(/\/$/, '')
  const eventName = sanitize(event.event)
  const distinctId = sanitize(event.distinct_id)

  return (
    <Box>
      <Text color={isSelected ? colors.orange : colors.textDim}>{prefix} </Text>
      <Box width={eventWidth}>
        <Text color={eventColor} bold={isSelected}>
          {truncate(eventName, eventWidth - 1)}
        </Text>
      </Box>
      <Box width={distinctIdWidth}>
        <Text color={isSelected ? colors.text : colors.textMuted}>
          {truncate(distinctId, distinctIdWidth - 1)}
        </Text>
      </Box>
      <Box width={urlWidth}>
        <Text color={colors.textDim}>
          {truncate(displayUrl, urlWidth - 1)}
        </Text>
      </Box>
      <Box width={timeWidth} justifyContent="flex-end">
        <Text color={colors.textDim}>
          {formatTimestamp(event.timestamp)}
        </Text>
      </Box>
    </Box>
  )
}

export const EventsTable = ({ events, selectedIndex, height }: EventsTableProps) => {
  // Get terminal width (default to 120 if not available)
  const width = process.stdout.columns || 120

  // Calculate visible window anchored to selected index
  const startIndex = Math.max(0, Math.min(selectedIndex, events.length - height))
  const visibleEvents = events.slice(startIndex, startIndex + height)

  return (
    <Box flexDirection="column" borderStyle="single" borderColor={colors.border} borderTop={false}>
      {/* Header */}
      <Box paddingX={1} borderStyle="single" borderColor={colors.border} borderLeft={false} borderRight={false} borderTop={false}>
        <Text color={colors.textMuted}>  </Text>
        <Box width={25}>
          <Text color={colors.textMuted} bold>Event</Text>
        </Box>
        <Box width={30}>
          <Text color={colors.textMuted} bold>Distinct ID</Text>
        </Box>
        <Box flexGrow={1}>
          <Text color={colors.textMuted} bold>URL</Text>
        </Box>
        <Box width={8} justifyContent="flex-end">
          <Text color={colors.textMuted} bold>Time</Text>
        </Box>
      </Box>

      {/* Events */}
      <Box flexDirection="column" paddingX={1}>
        {visibleEvents.length === 0 ? (
          <Box justifyContent="center" paddingY={2}>
            <Text color={colors.textDim}>Waiting for events...</Text>
          </Box>
        ) : (
          visibleEvents.map((event, index) => (
            <EventRow
              key={event.uuid}
              event={event}
              isSelected={index + startIndex === selectedIndex}
              width={width - 4}
            />
          ))
        )}
      </Box>
    </Box>
  )
}
