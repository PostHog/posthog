import React from 'react'
import { Box, Text } from 'ink'
import { colors } from '../colors.js'
import { sanitize, sanitizeJson } from '../sanitize.js'
import type { EventMsg } from '../../types.js'

type EventDetailProps = {
  event: EventMsg
  scrollOffset: number
  height: number
}

const formatValue = (value: unknown): string => {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (typeof value === 'string') return `"${sanitize(value)}"`
  if (typeof value === 'object') return sanitizeJson(value)
  return sanitize(value)
}

export const EventDetail = ({ event, scrollOffset, height }: EventDetailProps) => {
  const width = (process.stdout.columns || 120) - 8

  // Build content lines - sanitize all user-controlled fields
  const lines: Array<{ label?: string; value: string; color?: string }> = [
    { label: 'UUID', value: sanitize(event.uuid), color: colors.textMuted },
    { label: 'Event', value: sanitize(event.event), color: colors.orange },
    { label: 'Timestamp', value: new Date(event.timestamp as string).toISOString(), color: colors.text },
    { label: 'Distinct ID', value: sanitize(event.distinct_id), color: colors.blue },
    { label: 'Person ID', value: sanitize(event.person_id) || '(none)', color: colors.textMuted },
    { value: '' }, // Spacer
    { label: 'Properties', value: '', color: colors.yellow },
  ]

  // Add properties
  const sortedKeys = Object.keys(event.properties || {}).sort()
  for (const key of sortedKeys) {
    const value = event.properties[key]
    const formattedValue = formatValue(value)

    // Handle multi-line values
    const valueLines = formattedValue.split('\n')
    lines.push({ label: `  ${sanitize(key)}`, value: valueLines[0], color: colors.text })
    for (let i = 1; i < valueLines.length; i++) {
      lines.push({ value: `    ${valueLines[i]}`, color: colors.textDim })
    }
  }

  // Apply scroll offset
  const visibleLines = lines.slice(scrollOffset, scrollOffset + height - 4)

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={colors.orange}
      paddingX={2}
      paddingY={1}
    >
      <Box justifyContent="space-between" marginBottom={1}>
        <Text bold color={colors.orange}>Event Details</Text>
        <Text color={colors.textDim}>(esc to close, j/k to scroll)</Text>
      </Box>

      <Box flexDirection="column">
        {visibleLines.map((line, index) => (
          <Box key={index}>
            {line.label && (
              <Box width={20}>
                <Text color={colors.textMuted}>{line.label}:</Text>
              </Box>
            )}
            <Text color={line.color || colors.text} wrap="truncate">
              {line.value}
            </Text>
          </Box>
        ))}
      </Box>

      {lines.length > height - 4 && (
        <Box justifyContent="flex-end" marginTop={1}>
          <Text color={colors.textDim}>
            {scrollOffset + 1}-{Math.min(scrollOffset + height - 4, lines.length)} of {lines.length}
          </Text>
        </Box>
      )}
    </Box>
  )
}
