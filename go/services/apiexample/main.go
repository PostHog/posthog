package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/PostHog/posthog/go/pkg/common"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

type Server struct {
	config *common.PostHogConfig
	router *chi.Mux
}

func NewServer() (*Server, error) {
	config, err := common.NewPostHogConfig()
	if err != nil {
		return nil, err
	}

	r := chi.NewRouter()

	// Middleware
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))

	s := &Server{
		config: config,
		router: r,
	}

	s.routes()
	return s, nil
}

func (s *Server) routes() {
	s.router.Get("/health", s.handleHealth())
	s.router.Get("/config", s.handleConfig())
}

func (s *Server) handleHealth() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{
			"status": "ok",
			"time":   time.Now().Format(time.RFC3339),
		})
	}
}

func (s *Server) handleConfig() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{
			"host":        s.config.Host,
			"project_id":  s.config.ProjectID,
			"instance_id": s.config.InstanceID,
		})
	}
}

func main() {
	server, err := NewServer()
	if err != nil {
		log.Fatal(err)
	}

	srv := &http.Server{
		Addr:    ":8000",
		Handler: server.router,
	}

	// Start server in a goroutine
	go func() {
		log.Printf("Starting server on :8000")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %s\n", err)
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Shutting down server...")

	// Create shutdown context with timeout
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		log.Fatal("Server forced to shutdown:", err)
	}

	log.Println("Server exiting")
}
