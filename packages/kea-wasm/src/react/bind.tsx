import { BuiltLogic, LogicWrapper } from '../types'
import * as React from 'react'
import { useMountedLogic } from './hooks'
import { getContext } from '../kea/context'

export type BindPropsProps = {
  logic: LogicWrapper
  props: LogicWrapper['props']
  children: React.ReactNode
}

export function getOrCreateContextForLogicWrapper(logic: LogicWrapper) {
  let context = getContext().react.contexts.get(logic)
  if (!context) {
    context = React.createContext(undefined as BuiltLogic | undefined)
    getContext().react.contexts.set(logic, context)
  }
  return context
}

export function BindLogic({ logic, props, children }: BindPropsProps) {
  const LogicContext = getOrCreateContextForLogicWrapper(logic)
  const builtLogic = logic(props)

  useMountedLogic(builtLogic)

  return <LogicContext.Provider value={builtLogic}>{children}</LogicContext.Provider>
}
