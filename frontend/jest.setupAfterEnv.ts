import * as React from 'react'

global.React = React

// A require, not an import, because the taxonomy builds JSX and needs the global React set above.
// eslint-disable-next-line @typescript-eslint/no-require-imports
require('~/taxonomy/registerCoreFilterDefinitions')

// Loads every Lemon component before a test file can mock `kea`. A component that loads after such a
// mock binds the mocked hooks. LemonTable then reads no router values from `useValues` and throws.
// eslint-disable-next-line @typescript-eslint/no-require-imports
require('@posthog/lemon-ui')
