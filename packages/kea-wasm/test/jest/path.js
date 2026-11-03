import { kea, resetContext } from '../../src'

import React from 'react'

describe('path', () => {
  beforeEach(() => {
    resetContext()
  })

  describe('path', () => {
    test('works with and without function', () => {
      const logic1 = kea({
        path: ['this', 'is', 'logic1'],
        key: (props) => props.id,
      })
      const logic2 = kea({
        path: (id) => ['this', 'is', 'logic2', id],
        key: (props) => props.id,
      })
      const l1 = logic1({ id: 12 })
      l1.mount()
      expect(l1.path).toEqual(['this', 'is', 'logic1', 12])

      const l2 = logic2({ id: 12 })
      l2.mount()
      expect(l2.path).toEqual(['this', 'is', 'logic2', 12])
    })
  })
})
