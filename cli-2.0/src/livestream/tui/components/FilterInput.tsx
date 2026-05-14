import React, { useState } from 'react'
import { Box, Text, useInput } from 'ink'
import { colors } from '../colors.js'

type FilterInputProps = {
  type: 'event' | 'distinct'
  initialValue: string
  onSubmit: (value: string) => void
  onCancel: () => void
}

export const FilterInput = ({ type, initialValue, onSubmit, onCancel }: FilterInputProps) => {
  const [value, setValue] = useState(initialValue)

  useInput((input, key) => {
    if (key.return) {
      onSubmit(value)
    } else if (key.escape) {
      onCancel()
    } else if (key.backspace || key.delete) {
      setValue((prev) => prev.slice(0, -1))
    } else if (input && !key.ctrl && !key.meta) {
      setValue((prev) => prev + input)
    }
  })

  const label = type === 'event' ? 'Event type filter' : 'Distinct ID filter'
  const placeholder = type === 'event' ? '$pageview, $autocapture' : 'user_123'

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={colors.blue}
      paddingX={2}
      paddingY={1}
    >
      <Text color={colors.blue} bold>{label}</Text>
      <Box marginTop={1}>
        <Text color={colors.textMuted}>{'> '}</Text>
        <Text color={colors.text}>{value}</Text>
        <Text color={colors.orange}>█</Text>
      </Box>
      {!value && (
        <Text color={colors.textDim}>e.g., {placeholder}</Text>
      )}
      <Box marginTop={1} gap={2}>
        <Text color={colors.textDim}>Enter to apply</Text>
        <Text color={colors.textDim}>Esc to cancel</Text>
      </Box>
    </Box>
  )
}
