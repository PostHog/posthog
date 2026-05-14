import React from 'react'
import { Box, Text } from 'ink'
import { colors } from '../colors.js'

const shortcuts = [
  { key: 'p', description: 'Pause/resume event stream' },
  { key: 'f', description: 'Filter by event type' },
  { key: 'd', description: 'Filter by distinct ID' },
  { key: 'Enter', description: 'View event details' },
  { key: 'Esc', description: 'Close detail/filter view' },
  { key: 'j / ↓', description: 'Move cursor down' },
  { key: 'k / ↑', description: 'Move cursor up' },
  { key: 'x', description: 'Clear all events' },
  { key: '?', description: 'Toggle this help' },
  { key: 'q', description: 'Quit' },
]

export const HelpOverlay = () => {
  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={colors.orange}
      paddingX={3}
      paddingY={1}
    >
      <Box justifyContent="center" marginBottom={1}>
        <Text bold color={colors.orange}>Keyboard Shortcuts</Text>
      </Box>

      <Box flexDirection="column" gap={0}>
        {shortcuts.map(({ key, description }) => (
          <Box key={key} gap={2}>
            <Box width={12} justifyContent="flex-end">
              <Text color={colors.yellow}>{key}</Text>
            </Box>
            <Text color={colors.text}>{description}</Text>
          </Box>
        ))}
      </Box>

      <Box justifyContent="center" marginTop={1}>
        <Text color={colors.textDim}>Press Esc or ? to close</Text>
      </Box>
    </Box>
  )
}
