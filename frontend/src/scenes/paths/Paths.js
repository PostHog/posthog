import React, { Component } from 'react'
import api from '../../lib/api';
import PathFilter from './PathFilter'
import { toParams, Card } from '../../lib/utils'
import moment from 'moment'
import DateFilter from '../../lib/components/DateFilter';

let stripHTTP = (url) => url.replace(/(^[0-9]+_\w+:|^)\/\//, '');

function rounded_rect(x, y, w, h, r, tl, tr, bl, br) {
    var retval;
    retval  = "M" + (x + r) + "," + y;
    retval += "h" + (w - 2*r);
    if (tr) { retval += "a" + r + "," + r + " 0 0 1 " + r + "," + r; }
    else { retval += "h" + r; retval += "v" + r; }
    retval += "v" + (h - 2*r);
    if (br) { retval += "a" + r + "," + r + " 0 0 1 " + -r + "," + r; }
    else { retval += "v" + r; retval += "h" + -r; }
    retval += "h" + (2*r - w);
    if (bl) { retval += "a" + r + "," + r + " 0 0 1 " + -r + "," + -r; }
    else { retval += "h" + -r; retval += "v" + -r; }
    retval += "v" + (2*r - h);
    if (tl) { retval += "a" + r + "," + r + " 0 0 1 " + r + "," + -r; }
    else { retval += "v" + -r; retval += "h" + r; }
    retval += "z";
    return retval;
}

export default class Paths extends Component {
    constructor(props) {
        super(props)
        this.state = {
            filter: {
                dateFrom: null,
                dateTo: null
            },
            paths: {
                nodes: [],
                links: [],
            },
            d3Loaded: false,
            sankeyLoaded: false
        }
        this.fetchPaths = this.fetchPaths.bind(this);
        this.canvas = React.createRef();

        this.fetchPaths();
        import('d3').then((d3) => {
            this.d3 = d3;
            this.setState({d3Loaded: true})
        });
        import('d3-sankey').then((sankey) => {
            this.sankey = sankey;
            this.setState({sankeyLoaded: true})
        })
    }

    renderPaths = () => {
        const { paths } = this.state

        if (!this.state.d3Loaded || !this.state.sankeyLoaded) {
            return
        }

        const elements = document.querySelectorAll('.paths svg')
        elements.forEach(node => node.parentNode.removeChild( node ))

        if (paths.nodes.length === 0) {
            this.setState({rendered: true})
            return
        }

        this.setState({rendered: true})
        let width = this.canvas.current.offsetWidth;
        let height = this.canvas.current.offsetHeight;

        let svg = this.d3.select(this.canvas.current).append('svg')
            .style("background", "#fff")
            .style("width", width)
            .style("height", height);
        let sankey = new this.sankey.sankey()
            .nodeId(d => d.name)
            .nodeAlign(this.sankey.sankeyLeft)
            .nodeSort(null)
            .nodeWidth(15)
            // .nodePadding()
            .size([width, height])
        let color = (name) => this.d3.scaleOrdinal(this.d3.interpolateBlues())(name.replace(/ .*/, ''))

        const {nodes, links} = sankey({
            nodes: paths.nodes.map(d => Object.assign({}, d)),
            links: paths.links.map(d => Object.assign({}, d))
        });

        svg.append("g")
        .selectAll("rect")
        .data(nodes)
        .join("rect")
            .attr("x", d => d.x0 + 1)
            .attr("y", d => d.y0)
            .attr("height", d => d.y1 - d.y0)
            .attr("width", d => d.x1 - d.x0 - 2)
            .attr("fill", d => {
            let c;
            for (const link of d.sourceLinks) {
                if (c === undefined) c = link.color;
                else if (c !== link.color) c = null;
            }
            if (c === undefined) for (const link of d.targetLinks) {
                if (c === undefined) c = link.color;
                else if (c !== link.color) c = null;
            }
            return (this.d3.color(c) || this.d3.color('#dddddd')).darker(0.5);
            })
            // .attr("fill", d =>  'var(--blue)')
            .attr("opacity", 0.5)
        .append("title")
            .text(d => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`);

        const dropOffGradient = svg.append('defs').append('linearGradient')
            .attr('id', 'dropoff-gradient')
            .attr('gradientTransform', 'rotate(90)')

        dropOffGradient.append('stop')
            .attr('offset', '0%')
            .attr('stop-color', 'rgba(220,53,69,0.7)')

        dropOffGradient.append('stop')
            .attr('offset', '100%')
            .attr('stop-color', '#ffffff')

        const link = svg.append("g")
            .attr("fill", "none")
        .selectAll("g")
        .data(links)
        .join("g")
            .attr("stroke", d =>  'var(--blue)')
            .attr("opacity", 0.3)
            .style("mix-blend-mode", "multiply");

        link.append("path")
            .attr("d", this.sankey.sankeyLinkHorizontal())
            .attr("stroke-width", d => {
                return Math.max(1, d.width)
            })
            // .attr("stroke", d =>  'var(--info)')
            // .attr("opacity", 0.5)
            ;

        link
            .append('g')
            .append('path')
            .attr('d', (data, b, c) => {
                if(data.source.layer == 0) return;
                let height = (data.source.y1-data.source.y0) - data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0);
                return rounded_rect(0, 0, 30, height, Math.min(25, height), false, true, false, false);
            })
            .attr('fill', 'url(#dropoff-gradient)')
            .attr('stroke-width', 0)
            .attr('transform', (data) => {
                return 'translate(' + Math.round(data.source.x1) + ',' + Math.round(data.source.y0 + data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)) + ')';
            })
            .append('tspan')
                .text(d => {
                    return d.value - d.source.sourceLinks.reduce((prev, curr) => prev + curr.value, 0);
                })

        link.append("title")
            .text(d => `${d.source.name} → ${d.target.name}\n${d.value.toLocaleString()}`);

        svg.append("g")
            .style("font-size", "12px")
        .selectAll("text")
        .data(nodes)
        .join("text")
            .attr("x", d => d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6)
            .attr("y", d => (d.y1 + d.y0) / 2)
            .attr("dy", "0.35em")
            .attr("text-anchor", d => d.x0 < width / 2 ? "start" : "end")
            .attr('display', d => d.value > 0 ? 'inherit' : 'none')
            .text(d => stripHTTP(d.name))

        .append("tspan")
            .attr("fill-opacity", 0.7)
            .text(d => ` ${d.value.toLocaleString()}`);

        return svg.node();
    }

    fetchPaths = () => {
        const params = toParams(this.state.filter)

        api.get(`api/paths${params ? `/?${params}` : ''}`).then((paths) => {
            this.setState({paths: {
                nodes: [...paths.map((path) => ({name: path.source})), ...paths.map((path) => ({name: path.target}))],
                links: paths
            }}, this.renderPaths);

        })
    }

    updateFilter = (changes) => {
        this.setState({ filter: { ...this.state.filter, ...changes }, rendered: false }, this.fetchPaths)
    }

    render () {
        let { paths, rendered, filter } = this.state;

        return (
            <div>
                <h1>Paths</h1>
                <Card
                    title={<span>
                        <span className='float-right'>
                            <DateFilter onChange={(date_from, date_to) => this.updateFilter({date_from, date_to})} dateFrom={filter.date_from} dateTo={filter.date_to} />
                        </span>
                    </span>}>
                        <div ref={this.canvas} className='paths' style={{height: '90vh'}}>
                            {!rendered && <div className='loading-overlay' style={{paddingTop: '14rem'}}><div /><br />(This might take a while)</div>}
                            {rendered && paths && paths.nodes.length === 0 && <div>We don't have any data to show here. You might need to send us some frontend (JS) events, as we use the <pre style={{display: 'inline'}}>$current_url</pre> property to calculate paths.</div>}
                        </div>
                </Card>
            </div>
        );
    }
}
