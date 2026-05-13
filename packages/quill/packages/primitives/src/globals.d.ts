declare module '*.css'

declare const process:
    | {
          env?: {
              NODE_ENV?: string
          }
      }
    | undefined
