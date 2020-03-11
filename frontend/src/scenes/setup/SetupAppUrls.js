import React from 'react'
import { kea, useActions, useValues } from 'kea'

import { userLogic } from '../userLogic'

const defaultValue = 'https://'

const appUrlsLogic = kea({
  actions: () => ({
    addUrl: true,
    removeUrl: index => ({ index }),
    updateUrl: (index, value ) => ({ index, value }),
    saveAppUrls: true
  }),

  defaults: () => ({
    appUrls: state => userLogic.selectors.user(state).team.app_urls || [defaultValue]
  }),

  reducers: ({ actions }) => ({
    appUrls: [[defaultValue], {
      [actions.addUrl]: (state) => state.concat([defaultValue]),
      [actions.updateUrl]: (state, { index, value }) => Object.assign([...state], { [index]: value }),
      [actions.removeUrl]: (state, { index }) => {
        const newAppUrls = [...state]
        newAppUrls.splice(index, 1)
        return newAppUrls
      }
    }],
    isSaved: [false, {
      [actions.addUrl]: () => false,
      [actions.removeUrl]: () => false,
      [actions.updateUrl]: () => false,
      [userLogic.actions.userUpdateSuccess]: (state, { updateKey }) => updateKey === 'SetupAppUrls' || state
    }]
  }),

  listeners: ({ actions, values }) => ({
    [actions.saveAppUrls]: () => {
      userLogic.actions.userUpdateRequest({ team: { app_urls: values.appUrls } }, 'SetupAppUrls')
    }
  })
})

export function SetupAppUrls () {
  const { appUrls, isSaved } = useValues(appUrlsLogic)
  const { addUrl, removeUrl, updateUrl, saveAppUrls } = useActions(appUrlsLogic)

  return (
    <div>
      <label>What URLs will you be using PostHog on?</label>
      <form onSubmit={e => { e.preventDefault(); saveAppUrls() }}>
        {appUrls.map((url, index) => (
          <div key={index} style={{ marginBottom: 5 }}>
            <input
              value={url}
              onChange={(e) => updateUrl(index, e.target.value)}
              autoFocus={appUrls.count === 1 && appUrls[0] === defaultValue}
              style={{ display: 'inline-block', maxWidth: 400 }}
              type="url"
              className='form-control'
              placeholder={defaultValue}
            />
            {index > 0 ? <button className='btn btn-link' type="button" onClick={() => removeUrl(index)}>Remove</button> : null}
          </div>
        ))}
        <button className='btn btn-link' type="button" onClick={addUrl} style={{ padding: '5px 0', marginBottom: 15 }}>+ Add Another URL</button>
        <br />

        <button className='btn btn-success' type="submit">Save URLs</button>
        {isSaved && <span className='text-success' style={{ marginLeft: 10 }}>URLs saved.</span>}
      </form>
    </div>
  )
}
