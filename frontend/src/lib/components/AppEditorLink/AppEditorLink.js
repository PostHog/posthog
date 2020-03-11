import React, { useState } from 'react'
import { ChooseURLModal, appEditorUrl } from './ChooseURLModal'
import { useValues } from 'kea'
import { userLogic } from '../../../scenes/userLogic'

export function AppEditorLink ({ actionId, style, className, children }) {
  const [modalOpen, setModalOpen] = useState(false)
  const { user } = useValues(userLogic)
  const appUrls = user.team.app_urls

  return (
    <>
      <a
          href={appEditorUrl(actionId, appUrls && appUrls[0])}
          style={style}
          className={className}
          onClick={e => { e.preventDefault(); setModalOpen(true) }}
      >
          {children}
      </a>
      {modalOpen && <ChooseURLModal actionId={actionId} dismissModal={() => setModalOpen(false)} />}
    </>
  )
}
