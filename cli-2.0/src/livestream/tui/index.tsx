import React from 'react'
import { render } from 'ink'
import { App } from './App.js'
import type { LivestreamCredentials } from '../types.js'

type TuiOptions = {
  eventType?: string
  distinctId?: string
}

export const runTui = async (credentials: LivestreamCredentials, options: TuiOptions = {}) => {
  const { waitUntilExit } = render(
    <App
      credentials={credentials}
      initialEventFilter={options.eventType}
      initialDistinctIdFilter={options.distinctId}
    />,
    {
      exitOnCtrlC: true,
    }
  )

  await waitUntilExit()
}
