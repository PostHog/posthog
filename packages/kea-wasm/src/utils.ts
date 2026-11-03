import { BuiltLogic, LogicWrapper } from './types'

export function isLogicWrapper(logic: any): logic is LogicWrapper {
  return '_isKea' in logic
}

export function isBuiltLogic(logic: any): logic is BuiltLogic {
  return '_isKeaBuild' in logic
}

export const shallowCompare = (obj1: Record<string, any>, obj2: Record<string, any>) => {
  const keys1 = Object.keys(obj1)
  const keys2 = Object.keys(obj2)
  return keys1.length === keys2.length && keys1.every((key) => obj2.hasOwnProperty(key) && obj1[key] === obj2[key])
}
