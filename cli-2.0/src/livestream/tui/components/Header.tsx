import React from 'react'
import { Box, Text } from 'ink'
import { colors } from '../colors.js'
import { sanitize } from '../sanitize.js'

type HeaderProps = {
  teamName: string
  connectionState: 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'paused'
  isPaused: boolean
  eventFilter?: string
  distinctIdFilter?: string
}

const Logo = () => (
  <Box>
    <Text backgroundColor={colors.blue}> </Text>
    <Text backgroundColor={colors.orange}> </Text>
    <Text backgroundColor={colors.yellow}> </Text>
    <Text backgroundColor="#151619"> </Text>
    <Text> </Text>
  </Box>
)

const ConnectionBadge = ({ state }: { state: HeaderProps['connectionState'] }) => {
  const config = {
    connecting: { color: colors.warning, text: 'Connecting...' },
    connected: { color: colors.success, text: 'Connected' },
    reconnecting: { color: colors.warning, text: 'Reconnecting...' },
    disconnected: { color: colors.error, text: 'Disconnected' },
    paused: { color: colors.warning, text: 'Paused' },
  }

  const { color, text } = config[state]

  return (
    <Text color={color}>● {text}</Text>
  )
}

export const Header = ({
  teamName,
  connectionState,
  isPaused,
  eventFilter,
  distinctIdFilter,
}: HeaderProps) => {
  return (
    <Box
      borderStyle="single"
      borderColor={colors.border}
      paddingX={1}
      justifyContent="space-between"
    >
      <Box gap={2}>
        <Logo />
        <Text bold color={colors.orange}>PostHog Live</Text>
        <ConnectionBadge state={isPaused ? 'paused' : connectionState} />

        {eventFilter && (
          <Box gap={1}>
            <Text color={colors.textMuted}>event:</Text>
            <Text color={colors.blue}>{sanitize(eventFilter)}</Text>
            <Text color={colors.textDim}>[f]</Text>
          </Box>
        )}

        {distinctIdFilter && (
          <Box gap={1}>
            <Text color={colors.textMuted}>id:</Text>
            <Text color={colors.blue}>{sanitize(distinctIdFilter)}</Text>
            <Text color={colors.textDim}>[d]</Text>
          </Box>
        )}
      </Box>

      <Text color={colors.textMuted}>{sanitize(teamName)}</Text>
    </Box>
  )
}
