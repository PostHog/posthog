import React from 'react'
import { Box, Text } from 'ink'
import { colors } from '../colors.js'

type StatsBarProps = {
  eventsPerMinute: number
  totalEvents: number
}

export const StatsBar = ({ eventsPerMinute, totalEvents }: StatsBarProps) => {
  return (
    <Box
      borderStyle="single"
      borderColor={colors.border}
      borderTop={false}
      paddingX={1}
      gap={3}
    >
      <Box gap={1}>
        <Text color={colors.textMuted}>Events/min:</Text>
        <Text bold color={colors.orange}>{eventsPerMinute.toLocaleString()}</Text>
      </Box>

      <Box gap={1}>
        <Text color={colors.textMuted}>Total:</Text>
        <Text bold color={colors.text}>{totalEvents.toLocaleString()}</Text>
      </Box>
    </Box>
  )
}
