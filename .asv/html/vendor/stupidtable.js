/*
Copyright (c) 2012 Joseph McCullough

Permission is hereby granted, free of charge, to any person obtaining a copy   
of this software and associated documentation files (the "Software"), to deal   
in the Software without restriction, including without limitation the rights   
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell   
copies of the Software, and to permit persons to whom the Software is   
furnished to do so, subject to the following conditions:  

The above copyright notice and this permission notice shall be included in all  
copies or substantial portions of the Software.  

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR   
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,  
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER  
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE  
SOFTWARE.
*/

// Stupid jQuery table plugin.

;(function ($) {
    $.fn.stupidtable = function (sortFns) {
        return this.each(function () {
            var $table = $(this)
            sortFns = sortFns || {}
            sortFns = $.extend({}, $.fn.stupidtable.default_sort_fns, sortFns)
            $table.data('sortFns', sortFns)

            $table.on('click.stupidtable', 'thead th', function () {
                $(this).stupidsort()
            })
        })
    }

    // Expects $("#mytable").stupidtable() to have already been called.
    // Call on a table header.
    $.fn.stupidsort = function (force_direction) {
        var $this_th = $(this)
        var th_index = 0 // we'll increment this soon
        var dir = $.fn.stupidtable.dir
        var $table = $this_th.closest('table')
        var datatype = $this_th.data('sort') || null

        // No datatype? Nothing to do.
        if (datatype === null) {
            return
        }

        // Account for colspans
        $this_th
            .parents('tr')
            .find('th')
            .slice(0, $(this).index())
            .each(function () {
                var cols = $(this).attr('colspan') || 1
                th_index += parseInt(cols, 10)
            })

        var sort_dir
        if (arguments.length == 1) {
            sort_dir = force_direction
        } else {
            sort_dir = force_direction || $this_th.data('sort-default') || dir.ASC
            if ($this_th.data('sort-dir')) sort_dir = $this_th.data('sort-dir') === dir.ASC ? dir.DESC : dir.ASC
        }

        $table.trigger('beforetablesort', { column: th_index, direction: sort_dir })

        // More reliable method of forcing a redraw
        $table.css('display')

        // Run sorting asynchronously on a timout to force browser redraw after
        // `beforetablesort` callback. Also avoids locking up the browser too much.
        setTimeout(function () {
            // Gather the elements for this column
            var column = []
            var sortFns = $table.data('sortFns')
            var sortMethod = sortFns[datatype]
            var trs = $table.children('tbody').children('tr')

            // Extract the data for the column that needs to be sorted and pair it up
            // with the TR itself into a tuple. This way sorting the values will
            // incidentally sort the trs.
            trs.each(function (index, tr) {
                var $e = $(tr).children().eq(th_index)
                var sort_val = $e.data('sort-value')

                // Store and read from the .data cache for display text only sorts
                // instead of looking through the DOM every time
                if (typeof sort_val === 'undefined') {
                    var txt = $e.text()
                    $e.data('sort-value', txt)
                    sort_val = txt
                }
                column.push([sort_val, tr])
            })

            // Sort by the data-order-by value
            column.sort(function (a, b) {
                return sortMethod(a[0], b[0])
            })
            if (sort_dir != dir.ASC) column.reverse()

            // Replace the content of tbody with the sorted rows. Strangely
            // enough, .append accomplishes this for us.
            trs = $.map(column, function (kv) {
                return kv[1]
            })
            $table.children('tbody').append(trs)

            // Reset siblings
            $table.find('th').data('sort-dir', null).removeClass('sorting-desc sorting-asc')
            $this_th.data('sort-dir', sort_dir).addClass('sorting-' + sort_dir)

            $table.trigger('aftertablesort', { column: th_index, direction: sort_dir })
            $table.css('display')
        }, 10)

        return $this_th
    }

    // Call on a sortable td to update its value in the sort. This should be the
    // only mechanism used to update a cell's sort value. If your display value is
    // different from your sort value, use jQuery's .text() or .html() to update
    // the td contents, Assumes stupidtable has already been called for the table.
    $.fn.updateSortVal = function (new_sort_val) {
        var $this_td = $(this)
        if ($this_td.is('[data-sort-value]')) {
            // For visual consistency with the .data cache
            $this_td.attr('data-sort-value', new_sort_val)
        }
        $this_td.data('sort-value', new_sort_val)
        return $this_td
    }

    // ------------------------------------------------------------------
    // Default settings
    // ------------------------------------------------------------------
    $.fn.stupidtable.dir = { ASC: 'asc', DESC: 'desc' }
    $.fn.stupidtable.default_sort_fns = {
        int: function (a, b) {
            return parseInt(a, 10) - parseInt(b, 10)
        },
        float: function (a, b) {
            return parseFloat(a) - parseFloat(b)
        },
        string: function (a, b) {
            return a.localeCompare(b)
        },
        'string-ins': function (a, b) {
            a = a.toLocaleLowerCase()
            b = b.toLocaleLowerCase()
            return a.localeCompare(b)
        },
    }
})(jQuery)
