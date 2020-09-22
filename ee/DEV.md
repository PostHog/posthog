## Getting it up and running
`docker-compose -f ee/docker-compose.ch.yml up`

## Fixing broken frontend build
`docker run -it ee_web yarn build`

## Debugging in pycharm
- `docker-compose -f ee/docker-compose.ch.yml up db redis kafka clickhouse worker`
- set up different ENV variables (todo) 
