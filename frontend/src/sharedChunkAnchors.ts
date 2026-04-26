// Build-time entry. Imports + the export below keep these npm packages
// from being tree-shaken so esbuild's splitter places them in their own
// shared chunk, keeping the largest chunk under CloudFront's 10 MB cap.

import * as BaseUiReact from '@base-ui/react'
import * as TiptapCore from '@tiptap/core'
import * as HighlightJs from 'highlight.js'
import * as Kea from 'kea'
import * as KeaForms from 'kea-forms'
import * as KeaLoaders from 'kea-loaders'
import * as KeaLocalstorage from 'kea-localstorage'
import * as KeaRouter from 'kea-router'
import * as KeaSubscriptions from 'kea-subscriptions'
import * as KeaWindowValues from 'kea-window-values'
import * as PosthogJs from 'posthog-js'
import * as Re2Js from 're2js'
import * as React from 'react'
import * as ReactDom from 'react-dom'
import * as ReactDomClient from 'react-dom/client'
import * as Zod from 'zod'

import * as PosthogIcons from '@posthog/icons'
import * as PosthogRrweb from '@posthog/rrweb'

import * as Chart from 'lib/Chart'

export const __chunkAnchors = {
    BaseUiReact,
    Chart,
    HighlightJs,
    Kea,
    KeaForms,
    KeaLoaders,
    KeaLocalstorage,
    KeaRouter,
    KeaSubscriptions,
    KeaWindowValues,
    PosthogIcons,
    PosthogJs,
    PosthogRrweb,
    React,
    ReactDom,
    ReactDomClient,
    Re2Js,
    TiptapCore,
    Zod,
}
