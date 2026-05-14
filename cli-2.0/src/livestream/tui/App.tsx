import React, { useState, useEffect } from 'react'
import { Box, useApp, useInput, useStdout } from 'ink'
import { Header } from './components/Header.js'
import { StatsBar } from './components/StatsBar.js'
import { EventsTable } from './components/EventsTable.js'
import { EventDetail } from './components/EventDetail.js'
import { Footer } from './components/Footer.js'
import { HelpOverlay } from './components/HelpOverlay.js'
import { FilterInput } from './components/FilterInput.js'
import { useEventStream } from './hooks/useEventStream.js'
import type { LivestreamCredentials, EventMsg } from '../types.js'

type ViewMode = 'events' | 'detail' | 'help' | 'filterEvent' | 'filterDistinct'

type AppProps = {
  credentials: LivestreamCredentials
  initialEventFilter?: string
  initialDistinctIdFilter?: string
}

export const App = ({ credentials, initialEventFilter, initialDistinctIdFilter }: AppProps) => {
  const { exit } = useApp()
  const { stdout } = useStdout()

  const [mode, setMode] = useState<ViewMode>('events')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [detailEvent, setDetailEvent] = useState<EventMsg | null>(null)
  const [detailScrollOffset, setDetailScrollOffset] = useState(0)
  const [eventFilter, setEventFilter] = useState(initialEventFilter || '')
  const [distinctIdFilter, setDistinctIdFilter] = useState(initialDistinctIdFilter || '')

  const {
    events,
    state,
    eventsPerMinute,
    pause,
    resume,
    clear,
    isPaused,
  } = useEventStream({
    credentials,
    eventType: eventFilter || undefined,
    distinctId: distinctIdFilter || undefined,
  })

  // Calculate available height for events table
  const terminalHeight = stdout?.rows || 24
  const tableHeight = Math.max(5, terminalHeight - 8) // Header + StatsBar + Footer + borders

  // Keep selected index in bounds
  useEffect(() => {
    if (selectedIndex >= events.length) {
      setSelectedIndex(Math.max(0, events.length - 1))
    }
  }, [events.length, selectedIndex])

  useInput((input, key) => {
    // Global quit
    if (input === 'q') {
      exit()
      process.exit(0)
      return
    }

    // Handle filter input modes
    if (mode === 'filterEvent' || mode === 'filterDistinct') {
      return // FilterInput component handles its own input
    }

    // Help toggle
    if (input === '?') {
      setMode(mode === 'help' ? 'events' : 'help')
      return
    }

    // Escape - close overlays
    if (key.escape) {
      if (mode !== 'events') {
        setMode('events')
        setDetailScrollOffset(0)
      }
      return
    }

    // Help mode - only Esc works (handled above)
    if (mode === 'help') {
      return
    }

    // Detail mode
    if (mode === 'detail') {
      if (input === 'j' || key.downArrow) {
        setDetailScrollOffset((prev) => prev + 1)
      } else if (input === 'k' || key.upArrow) {
        setDetailScrollOffset((prev) => Math.max(0, prev - 1))
      }
      return
    }

    // Events mode
    if (mode === 'events') {
      if (input === 'p') {
        isPaused ? resume() : pause()
      } else if (input === 'f') {
        setMode('filterEvent')
      } else if (input === 'd') {
        setMode('filterDistinct')
      } else if (input === 'x') {
        clear()
        setSelectedIndex(0)
      } else if (key.return && events.length > 0) {
        setDetailEvent(events[selectedIndex])
        setMode('detail')
        setDetailScrollOffset(0)
      } else if (input === 'j' || key.downArrow) {
        setSelectedIndex((prev) => Math.min(events.length - 1, prev + 1))
      } else if (input === 'k' || key.upArrow) {
        setSelectedIndex((prev) => Math.max(0, prev - 1))
      }
    }
  })

  const handleFilterSubmit = (type: 'event' | 'distinct', value: string) => {
    if (type === 'event') {
      setEventFilter(value)
    } else {
      setDistinctIdFilter(value)
    }
    clear()
    setMode('events')
  }

  const handleFilterCancel = () => {
    setMode('events')
  }

  return (
    <Box flexDirection="column" height={terminalHeight}>
      <Header
        teamName={credentials.teamName || `Team ${credentials.teamId}`}
        connectionState={state}
        isPaused={isPaused}
        eventFilter={eventFilter}
        distinctIdFilter={distinctIdFilter}
      />

      <StatsBar eventsPerMinute={eventsPerMinute} totalEvents={events.length} />

      {mode === 'help' ? (
        <Box flexGrow={1} justifyContent="center" alignItems="center">
          <HelpOverlay />
        </Box>
      ) : mode === 'detail' && detailEvent ? (
        <EventDetail
          event={detailEvent}
          scrollOffset={detailScrollOffset}
          height={tableHeight}
        />
      ) : mode === 'filterEvent' ? (
        <Box flexGrow={1} justifyContent="center" alignItems="center">
          <FilterInput
            type="event"
            initialValue={eventFilter}
            onSubmit={(value) => handleFilterSubmit('event', value)}
            onCancel={handleFilterCancel}
          />
        </Box>
      ) : mode === 'filterDistinct' ? (
        <Box flexGrow={1} justifyContent="center" alignItems="center">
          <FilterInput
            type="distinct"
            initialValue={distinctIdFilter}
            onSubmit={(value) => handleFilterSubmit('distinct', value)}
            onCancel={handleFilterCancel}
          />
        </Box>
      ) : (
        <EventsTable
          events={events}
          selectedIndex={selectedIndex}
          height={tableHeight}
        />
      )}

      <Footer mode={mode === 'detail' ? 'detail' : mode === 'help' ? 'help' : 'events'} />
    </Box>
  )
}
