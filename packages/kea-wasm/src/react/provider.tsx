import React from 'react'

let warned = process.env.NODE_ENV === 'test'

export function Provider({ children }: { children: React.ReactNode }): JSX.Element {
  if (!warned) {
    console.warn(
      "[KEA] <Provider> is now a no-op and should be removed. If you need it for Redux, use react-redux's <Provider store={getContext().store} />, or use Kea's useSelector.",
    )
    warned = true
  }

  return <>{children}</>
}
