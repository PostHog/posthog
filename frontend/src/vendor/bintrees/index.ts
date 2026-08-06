// Vendored from bintrees@1.0.2 — https://github.com/vadimg/js_bintrees
// Ported to TypeScript with no algorithmic changes.
//
// Copyright (C) 2011 by Vadim Graboys
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

export type Comparator<T> = (a: T, b: T) => number
export type Callback<T> = (item: T) => void | boolean

class TreeNode<T> {
    data: T
    left: TreeNode<T> | null = null
    right: TreeNode<T> | null = null
    red: boolean = true

    constructor(data: T) {
        this.data = data
    }

    getChild(dir: boolean | 0 | 1): TreeNode<T> | null {
        return dir ? this.right : this.left
    }

    setChild(dir: boolean | 0 | 1, val: TreeNode<T> | null): void {
        if (dir) {
            this.right = val
        } else {
            this.left = val
        }
    }
}

function isRed<T>(node: TreeNode<T> | null): boolean {
    return node !== null && node.red
}

function singleRotate<T>(root: TreeNode<T>, dir: boolean | 0 | 1): TreeNode<T> {
    const save = root.getChild(!dir) as TreeNode<T>

    root.setChild(!dir, save.getChild(dir))
    save.setChild(dir, root)

    root.red = true
    save.red = false

    return save
}

function doubleRotate<T>(root: TreeNode<T>, dir: boolean | 0 | 1): TreeNode<T> {
    root.setChild(!dir, singleRotate(root.getChild(!dir) as TreeNode<T>, !dir))
    return singleRotate(root, dir)
}

export class Iterator<T> {
    private _tree: TreeBase<T>
    _ancestors: TreeNode<T>[] = []
    _cursor: TreeNode<T> | null = null

    constructor(tree: TreeBase<T>) {
        this._tree = tree
    }

    data(): T | null {
        return this._cursor !== null ? this._cursor.data : null
    }

    // if null-iterator, returns first node; otherwise next node
    next(): T | null {
        if (this._cursor === null) {
            const root = this._tree._root
            if (root !== null) {
                this._minNode(root)
            }
        } else {
            if (this._cursor.right === null) {
                let save: TreeNode<T> | null
                do {
                    save = this._cursor
                    if (this._ancestors.length) {
                        this._cursor = this._ancestors.pop() as TreeNode<T>
                    } else {
                        this._cursor = null
                        break
                    }
                } while (this._cursor.right === save)
            } else {
                this._ancestors.push(this._cursor)
                this._minNode(this._cursor.right)
            }
        }
        return this._cursor !== null ? this._cursor.data : null
    }

    // if null-iterator, returns last node; otherwise previous node
    prev(): T | null {
        if (this._cursor === null) {
            const root = this._tree._root
            if (root !== null) {
                this._maxNode(root)
            }
        } else {
            if (this._cursor.left === null) {
                let save: TreeNode<T> | null
                do {
                    save = this._cursor
                    if (this._ancestors.length) {
                        this._cursor = this._ancestors.pop() as TreeNode<T>
                    } else {
                        this._cursor = null
                        break
                    }
                } while (this._cursor.left === save)
            } else {
                this._ancestors.push(this._cursor)
                this._maxNode(this._cursor.left)
            }
        }
        return this._cursor !== null ? this._cursor.data : null
    }

    private _minNode(start: TreeNode<T>): void {
        while (start.left !== null) {
            this._ancestors.push(start)
            start = start.left
        }
        this._cursor = start
    }

    private _maxNode(start: TreeNode<T>): void {
        while (start.right !== null) {
            this._ancestors.push(start)
            start = start.right
        }
        this._cursor = start
    }
}

export abstract class TreeBase<T> {
    _root: TreeNode<T> | null = null
    _comparator: Comparator<T>
    size: number = 0

    constructor(comparator: Comparator<T>) {
        this._comparator = comparator
    }

    abstract insert(data: T): boolean
    abstract remove(data: T): boolean

    clear(): void {
        this._root = null
        this.size = 0
    }

    find(data: T): T | null {
        let res = this._root
        while (res !== null) {
            const c = this._comparator(data, res.data)
            if (c === 0) {
                return res.data
            }
            res = res.getChild(c > 0)
        }
        return null
    }

    findIter(data: T): Iterator<T> | null {
        let res = this._root
        const iter = this.iterator()

        while (res !== null) {
            const c = this._comparator(data, res.data)
            if (c === 0) {
                iter._cursor = res
                return iter
            }
            iter._ancestors.push(res)
            res = res.getChild(c > 0)
        }
        return null
    }

    // Returns an iterator at or immediately after the item
    lowerBound(item: T): Iterator<T> {
        let cur = this._root
        const iter = this.iterator()
        const cmp = this._comparator

        while (cur !== null) {
            const c = cmp(item, cur.data)
            if (c === 0) {
                iter._cursor = cur
                return iter
            }
            iter._ancestors.push(cur)
            cur = cur.getChild(c > 0)
        }

        for (let i = iter._ancestors.length - 1; i >= 0; --i) {
            cur = iter._ancestors[i]
            if (cmp(item, cur.data) < 0) {
                iter._cursor = cur
                iter._ancestors.length = i
                return iter
            }
        }

        iter._ancestors.length = 0
        return iter
    }

    // Returns an iterator immediately after the item
    upperBound(item: T): Iterator<T> {
        const iter = this.lowerBound(item)
        const cmp = this._comparator

        while (iter.data() !== null && cmp(iter.data() as T, item) === 0) {
            iter.next()
        }

        return iter
    }

    min(): T | null {
        let res = this._root
        if (res === null) {
            return null
        }
        while (res.left !== null) {
            res = res.left
        }
        return res.data
    }

    max(): T | null {
        let res = this._root
        if (res === null) {
            return null
        }
        while (res.right !== null) {
            res = res.right
        }
        return res.data
    }

    iterator(): Iterator<T> {
        return new Iterator<T>(this)
    }

    each(cb: Callback<T>): void {
        const it = this.iterator()
        let data: T | null
        while ((data = it.next()) !== null) {
            if (cb(data) === false) {
                return
            }
        }
    }

    reach(cb: Callback<T>): void {
        const it = this.iterator()
        let data: T | null
        while ((data = it.prev()) !== null) {
            if (cb(data) === false) {
                return
            }
        }
    }
}

export class RBTree<T> extends TreeBase<T> {
    constructor(comparator: Comparator<T>) {
        super(comparator)
    }

    // returns true if inserted, false if duplicate
    insert(data: T): boolean {
        let ret = false

        if (this._root === null) {
            this._root = new TreeNode<T>(data)
            ret = true
            this.size++
        } else {
            const head = new TreeNode<T>(undefined as unknown as T) // fake tree root

            let dir: boolean | 0 | 1 = 0
            let last: boolean | 0 | 1 = 0

            let gp: TreeNode<T> | null = null // grandparent
            let ggp: TreeNode<T> = head // grand-grand-parent
            let p: TreeNode<T> | null = null // parent
            let node: TreeNode<T> | null = this._root
            ggp.right = this._root

            while (true) {
                if (node === null) {
                    node = new TreeNode<T>(data)
                    ;(p as TreeNode<T>).setChild(dir, node)
                    ret = true
                    this.size++
                } else if (isRed(node.left) && isRed(node.right)) {
                    node.red = true
                    ;(node.left as TreeNode<T>).red = false
                    ;(node.right as TreeNode<T>).red = false
                }

                if (isRed(node) && isRed(p)) {
                    const dir2 = ggp.right === gp

                    if (node === (p as TreeNode<T>).getChild(last)) {
                        ggp.setChild(dir2, singleRotate(gp as TreeNode<T>, !last))
                    } else {
                        ggp.setChild(dir2, doubleRotate(gp as TreeNode<T>, !last))
                    }
                }

                const cmp = this._comparator(node.data, data)

                if (cmp === 0) {
                    break
                }

                last = dir
                dir = cmp < 0 ? 1 : 0

                if (gp !== null) {
                    ggp = gp
                }
                gp = p
                p = node
                node = node.getChild(dir)
            }

            this._root = head.right
        }

        ;(this._root as TreeNode<T>).red = false

        return ret
    }

    // returns true if removed, false if not found
    remove(data: T): boolean {
        if (this._root === null) {
            return false
        }

        const head = new TreeNode<T>(undefined as unknown as T) // fake tree root
        let node: TreeNode<T> = head
        node.right = this._root
        let p: TreeNode<T> | null = null
        let gp: TreeNode<T> | null = null
        let found: TreeNode<T> | null = null
        let dir: boolean | 0 | 1 = 1

        while (node.getChild(dir) !== null) {
            const last = dir

            gp = p
            p = node
            node = node.getChild(dir) as TreeNode<T>

            const cmp = this._comparator(data, node.data)

            dir = cmp > 0 ? 1 : 0

            if (cmp === 0) {
                found = node
            }

            if (!isRed(node) && !isRed(node.getChild(dir))) {
                if (isRed(node.getChild(!dir))) {
                    const sr = singleRotate(node, dir)
                    ;(p as TreeNode<T>).setChild(last, sr)
                    p = sr
                } else if (!isRed(node.getChild(!dir))) {
                    const sibling = (p as TreeNode<T>).getChild(!last)
                    if (sibling !== null) {
                        if (!isRed(sibling.getChild(!last)) && !isRed(sibling.getChild(last))) {
                            ;(p as TreeNode<T>).red = false
                            sibling.red = true
                            node.red = true
                        } else {
                            const dir2 = (gp as TreeNode<T>).right === p

                            if (isRed(sibling.getChild(last))) {
                                ;(gp as TreeNode<T>).setChild(dir2, doubleRotate(p as TreeNode<T>, last))
                            } else if (isRed(sibling.getChild(!last))) {
                                ;(gp as TreeNode<T>).setChild(dir2, singleRotate(p as TreeNode<T>, last))
                            }

                            const gpc = (gp as TreeNode<T>).getChild(dir2) as TreeNode<T>
                            gpc.red = true
                            node.red = true
                            ;(gpc.left as TreeNode<T>).red = false
                            ;(gpc.right as TreeNode<T>).red = false
                        }
                    }
                }
            }
        }

        if (found !== null) {
            found.data = node.data
            ;(p as TreeNode<T>).setChild((p as TreeNode<T>).right === node, node.getChild(node.left === null))
            this.size--
        }

        this._root = head.right
        if (this._root !== null) {
            this._root.red = false
        }

        return found !== null
    }
}

export class BinTree<T> extends TreeBase<T> {
    constructor(comparator: Comparator<T>) {
        super(comparator)
    }

    insert(data: T): boolean {
        if (this._root === null) {
            this._root = new TreeNode<T>(data)
            this.size++
            return true
        }

        let dir: boolean | 0 | 1 = 0
        let p: TreeNode<T> | null = null
        let node: TreeNode<T> | null = this._root

        while (true) {
            if (node === null) {
                node = new TreeNode<T>(data)
                ;(p as TreeNode<T>).setChild(dir, node)
                this.size++
                return true
            }

            if (this._comparator(node.data, data) === 0) {
                return false
            }

            dir = this._comparator(node.data, data) < 0 ? 1 : 0

            p = node
            node = node.getChild(dir)
        }
    }

    remove(data: T): boolean {
        if (this._root === null) {
            return false
        }

        const head = new TreeNode<T>(undefined as unknown as T)
        let node: TreeNode<T> = head
        node.right = this._root
        let p: TreeNode<T> | null = null
        let found: TreeNode<T> | null = null
        let dir: boolean | 0 | 1 = 1

        while (node.getChild(dir) !== null) {
            p = node
            node = node.getChild(dir) as TreeNode<T>
            const cmp = this._comparator(data, node.data)
            dir = cmp > 0 ? 1 : 0

            if (cmp === 0) {
                found = node
            }
        }

        if (found !== null) {
            found.data = node.data
            ;(p as TreeNode<T>).setChild((p as TreeNode<T>).right === node, node.getChild(node.left === null))

            this._root = head.right
            this.size--
            return true
        }
        return false
    }
}
