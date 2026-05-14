import React from 'react'
import { Box, Text } from 'ink'
import { colors } from '../colors.js'

type FooterProps = {
  mode: 'events' | 'detail' | 'help'
}

const Shortcut = ({ hotkey, label }: { hotkey: string; label: string }) => (
  <Box gap={0}>
    <Text color={colors.orange}>[{hotkey}]</Text>
    <Text color={colors.textMuted}> {label}</Text>
  </Box>
)

export const Footer = ({ mode }: FooterProps) => {
  return (
    <Box
      borderStyle="single"
      borderColor={colors.border}
      borderTop={false}
      paddingX={1}
      gap={2}
    >
      {mode === 'events' && (
        <>
          <Shortcut hotkey="p" label="pause" />
          <Shortcut hotkey="f" label="filter" />
          <Shortcut hotkey="d" label="distinct" />
          <Shortcut hotkey="↵" label="detail" />
          <Shortcut hotkey="x" label="clear" />
          <Shortcut hotkey="?" label="help" />
          <Shortcut hotkey="q" label="quit" />
        </>
      )}

      {mode === 'detail' && (
        <>
          <Shortcut hotkey="esc" label="back" />
          <Shortcut hotkey="j/k" label="scroll" />
          <Shortcut hotkey="q" label="quit" />
        </>
      )}

      {mode === 'help' && (
        <>
          <Shortcut hotkey="esc" label="close" />
          <Shortcut hotkey="q" label="quit" />
        </>
      )}
    </Box>
  )
}
